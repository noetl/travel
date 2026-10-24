#!/usr/bin/env python3
"""playbooks/itinerary-planner.yaml: extract_turn reads the turn with Claude
(claude-haiku-5-5) through the Anthropic API, the trip-intake v9 pattern
(noetl/travel#178), with Gemini on Vertex kept as llm_provider=vertex. Runs the
step's own code offline, every HTTP call stubbed.

  * the request: api.anthropic.com/v1/messages, x-api-key from Secret Manager,
    anthropic-version, anthropic-workspace-id, effort low, max_tokens 1024, thinking
    off unless claude_thinking=adaptive, no temperature, no JSON schema;
  * up to 8 s; a timeout is not retried; HTTP 429/5xx and dropped connections once;
  * the answer: text blocks only, refusals and cut-off answers fail;
  * the step: anthropic by default, vertex on request, widget events skip the
    model, any failure (or an invalid answer) leaves the keyword heuristic.
"""
import base64
import copy
import io
import json
import sys
import time
import urllib.error
import urllib.request

import yaml

PLAYBOOK = "playbooks/itinerary-planner.yaml"
doc = yaml.safe_load(open(PLAYBOOK))
steps = {s["step"]: s for s in doc["workflow"]}
step = steps["extract_turn"]
code = step["tool"]["code"]
WS = "wrkspc_01Ac7pHmUHKP8xGne1VEaZuB"
KEY = "sk-ant-test-key"

failures = []


def check(ok, label):
    print("%s %s" % ("PASS" if ok else "FAIL", label))
    if not ok:
        failures.append(label)


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code):
    return urllib.error.HTTPError("https://api.anthropic.com/v1/messages", code, "err", {}, io.BytesIO(b"{}"))


def claude_ok(obj, prose="", thinking=False):
    content = ([{"type": "thinking", "thinking": "", "signature": "x"}] if thinking else []) + \
        [{"type": "text", "text": prose + json.dumps(obj)}]
    return {"content": content, "stop_reason": "end_turn"}


class Net:
    """Stands in for urllib.request.urlopen: metadata token, Secret Manager, Claude, Gemini."""

    def __init__(self, claude=(), gemini=None, secret=KEY):
        self.claude = list(claude)
        self.gemini = gemini
        self.secret = secret
        self.calls, self.bodies, self.secret_reads = [], [], 0

    def __call__(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        headers = {k.lower(): v for k, v in req.header_items()} if hasattr(req, "header_items") else {}
        body = json.loads(req.data.decode("utf-8")) if getattr(req, "data", None) else None
        self.calls.append({"url": url, "headers": headers, "body": body, "timeout": timeout})
        if "metadata.google.internal" in url:
            return Resp(json.dumps({"access_token": "tok"}).encode())
        if "secretmanager.googleapis.com" in url:
            self.secret_reads += 1
            return Resp(json.dumps({"payload": {"data": base64.b64encode(self.secret.encode()).decode()}}).encode())
        if "api.anthropic.com" in url:
            self.bodies.append(body)
            item = self.claude.pop(0) if self.claude else TimeoutError("timed out")
            if isinstance(item, BaseException):
                raise item
            return Resp(json.dumps(item).encode())
        if "aiplatform.googleapis.com" in url:
            if self.gemini is None:
                raise TimeoutError("timed out")
            return Resp(json.dumps({"candidates": [{"content": {"parts": [{"text": json.dumps(self.gemini)}]}}]}).encode())
        raise AssertionError("unexpected call to %s" % url)

    def claude_calls(self):
        return [c for c in self.calls if "api.anthropic.com" in c["url"]]


def run(net, text, event_type="user_message", slots=None, payload=None, **over):
    g = {
        "thread_path": "chat_threads/test", "event_type": event_type,
        "event_payload": payload if payload is not None else {"text": text},
        "input_event": {}, "user_uid": "guest",
        "loaded_slot_state": {"data": copy.deepcopy(slots or {})},
        "ai_provider": "vertex-ai", "llm_extraction_model": "gemini-3.8-flash",
        "openai_api_key": "", "anthropic_api_key": "", "flight_provider": "duffel", "duffel_env": "test",
        "llm_extraction_enabled": True, "default_origin": "SFO",
        "vertex_project": "proj", "vertex_region": "global",
        "slm_backend": "gemini", "slm_endpoint": "", "slm_model": "", "slm_api_key": "",
        "llm_provider": "anthropic", "anthropic_model": "claude-haiku-5-5",
        "anthropic_secret_name": "shastara-eval", "anthropic_workspace_id": WS, "claude_thinking": "disabled",
    }
    g.update(over)
    real_urlopen, real_sleep = urllib.request.urlopen, time.sleep
    urllib.request.urlopen, time.sleep = net, (lambda s: net.calls.append({"url": "sleep", "s": s}))
    try:
        exec(compile(code, PLAYBOOK + ":extract_turn", "exec"), g)
    finally:
        urllib.request.urlopen, time.sleep = real_urlopen, real_sleep
    return g["result"]


LISBON = {"slot_updates": {"region": {"label": "Lisbon", "city_code": "LIS", "country_code": "PT"},
                           "party": {"adults": 2, "children": []}},
          "tool_requests": [{"tool": "mcp/hotelbeds.search_hotels", "arguments": {"destination": "LIS"}}],
          "render_intent": {"kind": "show_hotels"}}

# ── The request ──────────────────────────────────────────────────────────
net = Net(claude=[claude_ok(LISBON)])
r = run(net, "Hotels in Lisbon for 2 adults")
cc = net.claude_calls()
check(len(cc) == 1, "one call to the Anthropic Messages API")
c = cc[0]
check(c["url"] == "https://api.anthropic.com/v1/messages", "the Messages API URL")
check(c["headers"].get("x-api-key") == KEY and c["headers"].get("anthropic-version") == "2023-06-01"
      and c["headers"].get("anthropic-workspace-id") == WS, "x-api-key from the secret, anthropic-version, the workspace id")
b = c["body"]
check(b["model"] == "claude-haiku-5-5" and b["max_tokens"] == 1024 and b["output_config"] == {"effort": "low"},
      "claude-haiku-5-5, max_tokens 1024, effort low, no output schema")
check(b.get("thinking") == {"type": "disabled"} and "temperature" not in b and "top_p" not in b,
      "thinking off, no temperature (the API rejects it)")
turn = json.loads(b["messages"][0]["content"])
check(b["system"].startswith("You are the extraction pass") and turn["user_message"] == "Hotels in Lisbon for 2 adults"
      and turn["event_type"] == "user_message" and "slot_state" in turn and "today" in turn,
      "the planner's own prompt, and the turn as the Gemini path sends it")
check(c["timeout"] == 8, "8 s timeout")
sm = [x for x in net.calls if "secretmanager" in x["url"]][0]
check("projects/proj/secrets/shastara-eval/versions/latest:access" in sm["url"]
      and sm["headers"].get("authorization") == "Bearer tok", "the key is read from Secret Manager with the pod's token")
lc = r["llm_contract"]
check(lc["provider"] == "anthropic" and lc["model"] == "claude-haiku-5-5" and lc["fallback_used"] is False
      and "fallback_reason" not in lc, "llm_contract: anthropic, claude-haiku-5-5, answered by the model")
check(r["slot_state"].get("region", {}).get("city_code") == "LIS" and (r["slot_state"].get("party") or {}).get("adults") == 2
      and r["render_intent"].get("kind") == "collect_missing" and "dates" in (r["render_intent"].get("missing") or []),
      "the model's slots (Lisbon, 2 adults) land; the planner's own rule then asks for the hotel dates")
check(KEY not in json.dumps(r, default=str), "the key is not in the result")

net = Net(claude=[claude_ok(LISBON)])
run(net, "Hotels in Lisbon", claude_thinking="adaptive")
check("thinking" not in net.bodies[0], "claude_thinking=adaptive sends no thinking setting")
net = Net(claude=[claude_ok(LISBON)])
run(net, "Hotels in Lisbon", claude_thinking="")
check(net.bodies[0].get("thinking") == {"type": "disabled"}, "an empty claude_thinking means off")
net = Net(claude=[claude_ok(LISBON)])
run(net, "Hotels in Lisbon", claude_thinking="off")
check(net.bodies[0].get("thinking") == {"type": "disabled"}, "anything but \"adaptive\" means thinking off")
net = Net(claude=[claude_ok(LISBON)])
run(net, "Hotels in Lisbon", anthropic_workspace_id="wrkspc_OTHER")
check(net.claude_calls()[0]["headers"].get("anthropic-workspace-id") == "wrkspc_OTHER", "the workspace id comes from the input")

# ── Retries ──────────────────────────────────────────────────────────────
for exc, label in ((http_error(429), "HTTP 429"), (http_error(529), "HTTP 529"),
                   (ConnectionResetError("reset"), "a dropped connection")):
    net = Net(claude=[exc, claude_ok(LISBON)])
    r = run(net, "Hotels in Lisbon")
    sleeps = [x for x in net.calls if x["url"] == "sleep"]
    check(len(net.claude_calls()) == 2 and len(sleeps) == 1 and 0.5 <= sleeps[0]["s"] <= 1.5
          and r["llm_contract"]["fallback_used"] is False, "%s is retried once, after a short pause" % label)
for exc, label in ((TimeoutError("timed out"), "a timeout"), (http_error(400), "HTTP 400")):
    net = Net(claude=[exc, claude_ok(LISBON)])
    r = run(net, "Hotels in Lisbon")
    check(len(net.claude_calls()) == 1 and r["llm_contract"]["fallback_used"] is True,
          "%s is not retried: the heuristic answers" % label)
net = Net(claude=[urllib.error.URLError(TimeoutError("timed out")), claude_ok(LISBON)])
r = run(net, "Hotels in Lisbon")
check(len(net.claude_calls()) == 1 and r["llm_contract"]["fallback_used"] is True,
      "a timeout reported by urllib (URLError: timed out) is not retried either")
net = Net(claude=[http_error(503), http_error(503)])
r = run(net, "Hotels in Lisbon")
check(len(net.claude_calls()) == 2 and r["llm_contract"]["fallback_used"] is True
      and "503" in r["llm_contract"].get("fallback_reason", ""), "two failures: the heuristic answers and says why")

# ── The answer ───────────────────────────────────────────────────────────
for resp, label in ((claude_ok(LISBON, thinking=True), "thinking blocks are skipped"),
                    ({"content": [{"type": "text", "text": json.dumps(LISBON)}, {"type": "citations_delta", "text": "}"}],
                      "stop_reason": "end_turn"}, "only text blocks are read"),
                    (claude_ok(LISBON, prose="Here you go: "), "JSON wrapped in prose is found")):
    net = Net(claude=[resp])
    r = run(net, "Hotels in Lisbon")
    check(r["llm_contract"]["fallback_used"] is False and r["slot_state"].get("region", {}).get("city_code") == "LIS", label)
for resp, label in (({"content": [{"type": "text", "text": json.dumps(LISBON)}], "stop_reason": "refusal"}, "a refusal"),
                    ({"content": [{"type": "text", "text": json.dumps(LISBON)}], "stop_reason": "max_tokens"}, "a cut-off answer"),
                    ({"content": [{"type": "text", "text": "[1, 2]"}], "stop_reason": "end_turn"}, "a non-object"),
                    ({"content": [{"type": "text", "text": "no json here"}], "stop_reason": "end_turn"}, "no JSON"),
                    (claude_ok({"slot_updates": {"destination_city": "Lisbon"}, "render_intent": {"kind": "show_places"}}),
                     "an unknown slot key (validation)")):
    net = Net(claude=[resp])
    r = run(net, "Hotels in Lisbon")
    check(r["llm_contract"]["fallback_used"] is True and r["llm_contract"].get("fallback_reason"),
          "%s falls back to the heuristic" % label)

# ── The key ──────────────────────────────────────────────────────────────
net = Net(claude=[claude_ok(LISBON)], secret=json.dumps({"api_key": KEY}))
run(net, "Hotels in Lisbon")
check(net.claude_calls()[0]["headers"].get("x-api-key") == KEY, "a JSON secret {api_key} works too")
net = Net(claude=[claude_ok(LISBON)], secret="")
r = run(net, "Hotels in Lisbon")
check(not net.claude_calls() and r["llm_contract"]["fallback_used"] is True
      and "no API key" in r["llm_contract"].get("fallback_reason", ""), "an empty secret: no call, the heuristic answers")

# ── Provider, skips and switches ─────────────────────────────────────────
net = Net(gemini=LISBON)
r = run(net, "Hotels in Lisbon", llm_provider="vertex")
check(not net.claude_calls() and any("aiplatform.googleapis.com" in x["url"] for x in net.calls)
      and r["llm_contract"]["provider"] == "vertex-ai" and r["llm_contract"]["model"] == "gemini-3.8-flash"
      and r["llm_contract"]["fallback_used"] is False, "llm_provider=vertex is the Gemini rollback")
net = Net(claude=[TimeoutError("timed out")])
r = run(net, "Hotels in Lisbon")
check(r["llm_contract"]["fallback_used"] is True and "TimeoutError" in r["llm_contract"].get("fallback_reason", "")
      and r["render_intent"].get("kind"), "Claude timing out: the keyword heuristic still answers the turn")
net = Net(claude=[claude_ok(LISBON)])
r = run(net, None, event_type="user_widget_submit",
        payload={"action": "submit_dates", "check_in": "2026-11-03", "check_out": "2026-11-07"},
        slots={"region": {"label": "Lisbon", "city_code": "LIS", "country_code": "PT", "kind": "city"}})
check(not net.claude_calls() and "skipped" in r["llm_contract"].get("fallback_reason", ""),
      "a widget submit is parsed deterministically: no model call")
net = Net(claude=[claude_ok(LISBON)])
r = run(net, "Hotels in Lisbon", llm_extraction_enabled="false")
check(not net.claude_calls() and "disabled" in r["llm_contract"].get("fallback_reason", ""),
      "llm_extraction_enabled=false: no model call")

# ── The playbook ─────────────────────────────────────────────────────────
wl = doc["workload"]
check(wl.get("llm_provider") == "anthropic" and wl.get("anthropic_model") == "claude-haiku-5-5"
      and wl.get("anthropic_secret_name") == "shastara-eval" and wl.get("anthropic_workspace_id") == WS
      and wl.get("claude_thinking") == "disabled" and wl.get("llm_extraction_model") == "gemini-3.8-flash",
      "workload: Claude Haiku by default, the key's secret, the ranch workspace, thinking off, Gemini kept")
inp = step["tool"]["input"]
check(all(k in inp for k in ("llm_provider", "anthropic_model", "anthropic_secret_name", "anthropic_workspace_id", "claude_thinking"))
      and "default('anthropic')" in inp["llm_provider"] and "default('disabled')" in inp["claude_thinking"],
      "the step receives every Claude setting; with none set it reads with Claude, thinking off")
check("json_schema" not in code and "ai:anthropic" in doc["metadata"].get("capabilities", []),
      "free JSON (no output schema); the ai:anthropic capability")

print("%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
