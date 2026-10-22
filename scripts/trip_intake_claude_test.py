#!/usr/bin/env python3
"""playbooks/trip-intake.yaml: the reader calls Claude (claude-haiku-5-5) through the
Anthropic API, the Mount Shasta Ranch pattern, with Gemini on Vertex kept as
llm_provider=vertex. Runs the intake step's own code offline, every HTTP call stubbed.

  * the request: api.anthropic.com/v1/messages, x-api-key from Secret Manager,
    anthropic-version, anthropic-workspace-id, effort low, max_tokens 1024, no
    temperature, no JSON schema (free JSON; the reader's schema is over the API's
    optional-field limit), thinking off unless claude_thinking=adaptive;
  * up to 8 s; a timeout is not retried; HTTP 429/5xx and dropped connections once;
  * the answer: text blocks (thinking skipped), refusals and cut-off answers fail;
  * the key: raw or JSON in the secret, read once per process, never in a result;
  * the step: anthropic by default, vertex on request, a failure falls back to rules.
"""
import base64
import io
import json
import sys
import urllib.error
import urllib.request
from datetime import date

import yaml

failures = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


doc = yaml.safe_load(open("playbooks/trip-intake.yaml"))
steps = {s["step"]: s for s in doc["workflow"]}
code = steps["intake_turn"]["tool"]["code"]
TODAY = date(2026, 10, 23)
KEY = "sk-ant-TESTKEY-not-a-real-key-0123456789"
WS = "wrkspc_01Ac7pHmUHKP8xGne1VEaZuB"


class Resp(io.BytesIO):
    def __init__(self, body):
        super().__init__(json.dumps(body).encode())
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def http_error(code):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(b"{}"))


def claude_ok(obj, thinking=False, prose=""):
    content = ([{"type": "thinking", "thinking": "", "signature": "x"}] if thinking else []) + \
              [{"type": "text", "text": prose + json.dumps(obj)}]
    return Resp({"content": content, "stop_reason": "end_turn"})


class Net:
    def __init__(self, secret=KEY):
        self.secret, self.calls, self.queue, self.secret_reads = secret, [], [], 0

    def __call__(self, req, timeout=None):
        url = req.full_url
        if "metadata.google.internal" in url:
            return Resp({"access_token": "t"})
        if "secretmanager.googleapis.com" in url:
            self.secret_reads += 1
            return Resp({"payload": {"data": base64.b64encode(self.secret.encode()).decode()}})
        self.calls.append({"url": url, "timeout": timeout, "headers": {k.lower(): v for k, v in req.header_items()},
                           "body": json.loads(req.data.decode()) if req.data else None})
        nxt = self.queue.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


def fresh_lib(net):
    lib = {"_INTAKE_LIBRARY_ONLY": True}
    exec(code, lib)
    lib["urllib"].request.urlopen = net
    return lib


def read(net, *outcomes, **kw):
    lib = fresh_lib(net)
    net.queue = list(outcomes)
    sleeps = []
    try:
        out = lib["claude_read"]("A flight to Rome", {}, [], TODAY, "claude-haiku-5-5", "proj", "shastara-eval", WS,
                                 sleep=sleeps.append, **kw)
        return out, sleeps, None, lib
    except Exception as exc:  # noqa: BLE001
        return None, sleeps, exc, lib


# ── The request ──────────────────────────────────────────────────────────
net = Net()
out, sleeps, err, lib = read(net, claude_ok({"intent": "flight"}))
c = net.calls[0]
check(out == {"intent": "flight"} and c["url"] == "https://api.anthropic.com/v1/messages", "one call to the Anthropic Messages API")
check(c["headers"].get("x-api-key") == KEY and c["headers"].get("anthropic-version") == "2023-06-01"
      and c["headers"].get("anthropic-workspace-id") == WS, "x-api-key from the secret, anthropic-version, the workspace id")
b = c["body"]
check(b["model"] == "claude-haiku-5-5" and b["max_tokens"] == 1024 and b["output_config"] == {"effort": "low"},
      "claude-haiku-5-5, max_tokens 1024, effort low")
check("temperature" not in b and "top_p" not in b and b.get("thinking") == {"type": "disabled"},
      "no temperature (the API rejects it), no schema, thinking off by default")
check(b["system"] == lib["LLM_SYSTEM_PROMPT"] and json.loads(b["messages"][0]["content"])["message"] == "A flight to Rome",
      "the same prompt and message as the Gemini reader")
check(c["timeout"] == 8, "8 s timeout")
net = Net()
out, sleeps, err, lib = read(net, claude_ok({"intent": "hotel"}), thinking="adaptive")
b = net.calls[0]["body"]
check("thinking" not in b and b["output_config"] == {"effort": "low"}, "claude_thinking=adaptive leaves thinking to the model")
check('"A room" is rooms 1' in lib["LLM_SYSTEM_PROMPT"], "the prompt says \"a room\" is 1 room (the eval's Bel-Air miss)")

# ── Retries ──────────────────────────────────────────────────────────────
for exc, label in ((http_error(429), "HTTP 429"), (http_error(529), "HTTP 529 (overloaded)"), (ConnectionResetError("reset"), "a dropped connection")):
    net = Net()
    out, sleeps, err, lib = read(net, exc, claude_ok({"intent": "both"}))
    check(out == {"intent": "both"} and len(net.calls) == 2 and len(sleeps) == 1 and 0.5 <= sleeps[0] <= 1.5,
          "%s is retried once, after a 0.5-1.5 s pause" % label)
net = Net()
out, sleeps, err, lib = read(net, TimeoutError("timed out"), claude_ok({"intent": "both"}))
check(isinstance(err, TimeoutError) and len(net.calls) == 1, "a timeout is not retried")
net = Net()
out, sleeps, err, lib = read(net, http_error(400), claude_ok({"intent": "both"}))
check(isinstance(err, urllib.error.HTTPError) and len(net.calls) == 1, "HTTP 400 is not retried")
net = Net()
out, sleeps, err, lib = read(net, http_error(503), http_error(503))
check(err is not None and len(net.calls) == 2, "two fast failures: give up")

# ── The answer ───────────────────────────────────────────────────────────
for resp, want, label in [
    (claude_ok({"adults": 2}, thinking=True), {"adults": 2}, "thinking blocks are skipped"),
    (claude_ok({"adults": 3}, prose="Here it is: "), {"adults": 3}, "JSON inside prose is found"),
]:
    net = Net()
    out, _, err, _ = read(net, resp)
    check(out == want, label)
for resp, label in [
    (Resp({"content": [{"type": "text", "text": "{\"intent\": \"hotel\"}"}], "stop_reason": "refusal"}),
     "a refusal fails even if its text parses (the turn falls back)"),
    (Resp({"content": [{"type": "text", "text": "{\"adults\": 2}"}], "stop_reason": "max_tokens"}),
     "a cut-off answer fails even if what arrived parses"),
    (Resp({"content": [{"type": "text", "text": "no json here"}], "stop_reason": "end_turn"}), "no JSON fails"),
    (Resp({"content": [{"type": "text", "text": "[1, 2]"}], "stop_reason": "end_turn"}), "a JSON array is not an answer"),
]:
    net = Net()
    out, _, err, _ = read(net, resp)
    check(out is None and isinstance(err, ValueError), label)

# ── The key ──────────────────────────────────────────────────────────────
net = Net(secret=json.dumps({"api_key": KEY}))
out, _, err, lib = read(net, claude_ok({}))
check(net.calls[0]["headers"].get("x-api-key") == KEY, "a JSON secret {api_key} works too")
net = Net(secret="  \n")
out, _, err, lib = read(net, claude_ok({}))
check(isinstance(err, ValueError) and net.calls == [], "an empty secret fails before calling the API")
net = Net()
lib = fresh_lib(net)
net.queue = [claude_ok({}), claude_ok({})]
for _ in range(2):
    lib["claude_read"]("x", {}, [], TODAY, "claude-haiku-5-5", "proj", "shastara-eval", WS, sleep=lambda s: None)
check(net.secret_reads == 1, "the key is read from Secret Manager once per process")

# No JSON-schema switch: the live eval found the reader's schema over the API's limit of
# 24 optional fields, so every call was rejected and quietly answered by the rules.
check("CLAUDE_SCHEMA" not in lib and "json_schema" not in code and "claude_structured" not in yaml.safe_dump(doc),
      "no JSON-schema output and no switch for it")

# ── The step ─────────────────────────────────────────────────────────────
head, body_code = code.split("# ── The turn ", 1)
wl = doc["workload"]
check(wl.get("llm_provider") == "anthropic" and wl.get("anthropic_model") == "claude-haiku-5-5"
      and wl.get("anthropic_secret_name") == "shastara-eval" and wl.get("anthropic_workspace_id") == WS
      and wl.get("claude_thinking") == "disabled" and wl.get("llm_model") == "gemini-3.8-flash",
      "workload: Claude Haiku by default, the key's secret, the ranch workspace, Gemini kept for rollback")
inp = steps["intake_turn"]["tool"]["input"]
check(all(k in inp for k in ("llm_provider", "anthropic_model", "anthropic_secret_name", "anthropic_workspace_id",
                             "claude_thinking")), "the step receives every Claude setting")
check("default('disabled')" in inp["claude_thinking"] and "default('anthropic')" in inp["llm_provider"],
      "with no workload setting the step still reads with Claude, thinking off")


def step(net, text, **over):
    g = {"thread_path": "chat_threads/chat-c1", "event_payload": {"text": text},
         "input_event": {"type": "user_message", "payload": {"text": text}}, "loaded_state": {"found": False},
         "relation_docs": [], "llm_enabled": True, "llm_model": "gemini-3.8-flash", "vertex_project": "p",
         "vertex_region": "global", "today_override": TODAY.isoformat(), "firestore_project": "proj",
         "firestore_database": "(default)", "anthropic_model": "claude-haiku-5-5", "anthropic_secret_name": "shastara-eval",
         "anthropic_workspace_id": WS, "claude_thinking": "disabled"}
    g.update(over)
    exec(head, g)
    g["urllib"].request.urlopen = net
    g["time"].sleep = lambda s: None
    exec("# ── The turn " + body_code, g)
    return g["result"]


class StepNet(Net):
    """Claude / Vertex answers by host; Firestore cache misses."""
    def __init__(self, claude=None, vertex=None):
        super().__init__()
        self.claude, self.vertex = claude, vertex

    def __call__(self, req, timeout=None):
        url = req.full_url
        if "firestore.googleapis.com" in url:
            raise http_error(404)
        if "api.anthropic.com" in url:
            self.calls.append(url)
            self.bodies = getattr(self, "bodies", []) + [json.loads(req.data.decode())]
            if isinstance(self.claude, BaseException):
                raise self.claude
            return self.claude
        if "aiplatform.googleapis.com" in url:
            self.calls.append(url)
            return self.vertex
        return Net.__call__(self, req, timeout)


patch = {"intent": "flight", "destination": {"text": "Munich", "kind": "city", "airports": ["MUC"]}}
net = StepNet(claude=claude_ok(patch))
r = step(net, "A flight to Munich", llm_provider="anthropic")
check(r["llm"]["used"] and r["llm"]["provider"] == "anthropic" and r["llm"]["model"] == "claude-haiku-5-5"
      and r["intake_state"].get("destination_code") == "MUC" and all("api.anthropic.com" in u for u in net.calls),
      "the step reads with Claude by default and uses its answer")
check(KEY not in json.dumps(r), "the key appears nowhere in the step's result")
net = StepNet(claude=claude_ok(patch))
r = step(net, "A flight to Munich", llm_provider="bogus")
check(r["llm"]["provider"] == "anthropic", "an unknown provider means Claude")
vertex_body = Resp({"candidates": [{"content": {"parts": [{"text": json.dumps(patch)}]}}]})
net = StepNet(vertex=vertex_body)
r = step(net, "A flight to Munich", llm_provider="vertex")
check(r["llm"]["used"] and r["llm"]["provider"] == "vertex" and r["llm"]["model"] == "gemini-3.8-flash"
      and all("aiplatform.googleapis.com" in u for u in net.calls), "llm_provider=vertex is the Gemini rollback")
net = StepNet(claude=TimeoutError("timed out"))
r = step(net, "A flight to Maui from SFO", llm_provider="anthropic")
check(not r["llm"]["used"] and "TimeoutError" in r["llm"]["fallback_reason"] and r["intake_state"].get("destination_code") == "OGG",
      "Claude timing out: the rules and the island list answer (Maui -> OGG)")
net = StepNet(claude=claude_ok(patch))
r = step(net, "A flight to Munich", llm_provider="anthropic", claude_thinking="disabled")
check(r["llm"]["used"] and net.bodies[0].get("thinking") == {"type": "disabled"},
      "claude_thinking=\"disabled\" (a string from the template) reaches the request")
net = StepNet(claude=claude_ok(patch))
r = step(net, "A flight to Munich", llm_provider="anthropic", claude_thinking="adaptive")
check("thinking" not in net.bodies[0], "claude_thinking=\"adaptive\" sends nothing")
net = StepNet(claude=claude_ok(patch))
r = step(net, "A flight to Munich", llm_provider="anthropic", claude_thinking="")
check(net.bodies[0].get("thinking") == {"type": "disabled"}, "an empty claude_thinking means off")
net = StepNet(claude=claude_ok(patch))
r = step(net, "A flight to Munich", llm_provider="anthropic", anthropic_workspace_id="wrkspc_OTHER")
check(r["llm"]["used"], "the workspace id comes from the workload")

if failures:
    sys.exit("%d failure(s)" % len(failures))
