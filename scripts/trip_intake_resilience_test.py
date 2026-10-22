#!/usr/bin/env python3
"""playbooks/trip-intake.yaml: the model call is bounded and retried once, and place
facts are cached (adiona/frontend#55, after 2 of 5 prod
turns timed out). Runs the intake step's own code offline, every HTTP call stubbed.

  * llm_read: 7 s per try, one retry after a 0.5-1.5 s pause on a timeout, a dropped
    connection, HTTP 429 or 5xx; other errors fail at once. No responseSchema: measured
    live, it made the model drop the destination and invent keys.
  * use_place_cache: a fresh cached entry is used; an expired or invalid one is read
    again; a manual one always wins and is never overwritten; table places, hotels and
    airport codes are not cached; a broken cache never breaks a turn.
  * The step end to end: the model down + a cached Napa still offers Napa's nearest
    airports; a model reading of a new place is stored through the turn's own save.
"""
import io
import json
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

import yaml

failures = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


doc = yaml.safe_load(open("playbooks/trip-intake.yaml"))
steps = {s["step"]: s for s in doc["workflow"]}
code = steps["intake_turn"]["tool"]["code"]
lib = {"_INTAKE_LIBRARY_ONLY": True}
exec(code, lib)
TODAY = date(2026, 10, 21)
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


class Resp(io.BytesIO):
    def __init__(self, body):
        super().__init__(json.dumps(body).encode())
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def vertex_ok(patch):
    return Resp({"candidates": [{"content": {"parts": [{"text": json.dumps(patch)}]}}]})


def http_error(code):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(b"{}"))


calls = []


def scripted(*outcomes):
    """urlopen that plays the outcomes in order for Vertex calls (Exception -> raised)."""
    queue = list(outcomes)

    def urlopen(req, timeout=None):
        url = req.full_url
        if "metadata.google.internal" in url:
            return Resp({"access_token": "t"})
        calls.append((url, timeout, json.loads(req.data.decode()) if req.data else None))
        nxt = queue.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt
    return urlopen


def read(*outcomes):
    calls.clear()
    sleeps = []
    lib["urllib"].request.urlopen = scripted(*outcomes)
    try:
        out = lib["llm_read"]("A flight to Rome", {}, [], TODAY, "m", "p", "global", sleep=sleeps.append)
        return out, sleeps, None
    except Exception as exc:  # noqa: BLE001
        return None, sleeps, exc


# ── The bounded, retried model call ──────────────────────────────────────
out, sleeps, err = read(vertex_ok({"intent": "flight"}))
check(out == {"intent": "flight"} and sleeps == [] and calls[0][1] == 7, "one call, 7 s timeout")
body = calls[0][2]
check("responseSchema" not in body["generationConfig"] and body["generationConfig"]["temperature"] == 0,
      "no responseSchema (measured live: it made the model drop the destination and invent keys)")
out, sleeps, err = read(TimeoutError("timed out"), vertex_ok({"intent": "hotel"}))
check(out == {"intent": "hotel"} and len(sleeps) == 1 and 0.5 <= sleeps[0] <= 1.5 and len(calls) == 2,
      "a timeout is retried once, after a 0.5-1.5 s pause")
out, sleeps, err = read(urllib.error.URLError("timed out"), vertex_ok({"intent": "hotel"}))
check(out == {"intent": "hotel"} and len(calls) == 2, "a dropped connection is retried")
out, sleeps, err = read(http_error(429), vertex_ok({"intent": "both"}))
check(out == {"intent": "both"} and len(calls) == 2, "HTTP 429 is retried")
out, sleeps, err = read(http_error(503), vertex_ok({"intent": "both"}))
check(out == {"intent": "both"} and len(calls) == 2, "HTTP 5xx is retried")
out, sleeps, err = read(TimeoutError("timed out"), TimeoutError("timed out"))
check(isinstance(err, TimeoutError) and len(calls) == 2 and len(sleeps) == 1, "two timeouts: give up (the turn falls back)")
out, sleeps, err = read(http_error(400), vertex_ok({"intent": "flight"}))
check(isinstance(err, urllib.error.HTTPError) and len(calls) == 1 and sleeps == [], "HTTP 400 is not retried")
check(lib["LLM_ATTEMPTS"] * lib["LLM_TIMEOUT_S"] + 1.5 <= 16, "worst case about 15 s")

# ── The place-facts cache ────────────────────────────────────────────────
use = lib["use_place_cache"]
NAPA = {"kind": "city", "lat": 38.2975, "lon": -122.2869, "airports": []}
fresh = {"facts": NAPA, "source": "model", "expires_at": (NOW + timedelta(days=5)).isoformat()}
out, writes, used = use({"destination": {"text": "Napa", "kind": "city", "lat": 1.0, "lon": 1.0}}, lambda k: fresh, NOW)
check(out["destination"]["lat"] == 38.2975 and used == ["napa"] and writes == [], "a fresh cached entry is used, the model's facts ignored")
out, writes, used = use({"destination": {"text": "napa", "kind": "city"}}, lambda k: dict(fresh) if k == "napa" else None, NOW)
check(out["destination"]["lon"] == -122.2869, "the cache key ignores case")
expired = dict(fresh, expires_at=(NOW - timedelta(days=1)).isoformat())
out, writes, used = use({"destination": dict(NAPA, text="Napa")}, lambda k: expired, NOW)
check(used == [] and len(writes) == 1 and writes[0]["path"] == "intake_place_facts/napa", "an expired entry is read again and replaced")
w = writes[0]["doc"]
check(json.loads(w["facts_json"]) == {"kind": "city", "lat": 38.2975, "lon": -122.2869} and w["source"] == "model"
      and w["expires_at"] == (NOW + timedelta(days=30)).isoformat() and writes[0]["merge"] is False,
      "what is stored: the facts, model as the source, a 30-day expiry")
out, writes, used = use({"destination": dict(NAPA, text="Napa")}, lambda k: dict(fresh, invalid=True), NOW)
check(used == [] and len(writes) == 1, "an entry marked invalid is replaced by the next reading")
manual = {"facts": {"kind": "city", "lat": 1.5, "lon": 2.5}, "source": "manual", "expires_at": "2000-01-01"}
out, writes, used = use({"destination": dict(NAPA, text="Napa")}, lambda k: manual, NOW)
check(out["destination"]["lat"] == 1.5 and writes == [], "a manual entry always wins, expired or not, and is never overwritten")
out, writes, used = use({"destination": dict(NAPA, text="Napa")}, lambda k: dict(manual, invalid=True), NOW)
check(used == [] and writes == [], "a manual entry marked invalid is skipped, but the model never overwrites it")
out, writes, used = use({"destination": {"text": "Napa", "kind": "city"}}, lambda k: None, NOW)
check(writes == [], "a reading with no facts is not stored")
looked = []
for place in ({"text": "Maui", "kind": "island", "airports": ["OGG"]}, {"text": "Hotel Bel-Air", "kind": "hotel", "lat": 1, "lon": 1},
              {"text": "LHR", "kind": "airport"}, {"text": "SFO", "kind": "city", "airports": ["SFO"]}):
    out, writes, used = use({"destination": place}, lambda k: looked.append(k), NOW)
check(looked == [] and writes == [], "table places, hotels and airport codes are neither looked up nor stored")
out, writes, used = use({"destination": dict(NAPA, text="Napa")}, lambda k: 1 / 0, NOW)
check(out["destination"]["lat"] == 38.2975 and len(writes) == 1, "a failing lookup is a miss, not an error")
out, writes, used = use({"origin": dict(NAPA, text="Napa")}, lambda k: None, NOW)
check(len(writes) == 1, "the origin is cached too")

# The words after to/in/from are tried against the cache when the reader found no place.
asked_keys = []
out, writes, used = use({}, lambda k: asked_keys.append(k) or (fresh if k == "napa" else None), NOW, "Flights to Napa from Boise")
check(out.get("destination", {}).get("text") == "Napa" and out["destination"]["lat"] == 38.2975 and writes == [],
      "a cached place after 'to' becomes the destination (and nothing is stored)")
check("origin" not in out and "boise" in asked_keys, "a cache miss after 'from' adds nothing")
asked_keys.clear()
out, writes, used = use({}, lambda k: asked_keys.append(k) or (fresh if k == "napa-valley" else None), NOW, "A hotel in Napa Valley please")
check(out.get("destination", {}).get("text") == "Napa Valley" and asked_keys[0] == "napa-valley", "the longest name is tried first")
out, writes, used = use({"destination": {"text": "Rome", "kind": "city"}}, lambda k: fresh, NOW, "Flights to Napa")
check(out["destination"]["text"] == "Rome", "a place the reader already found is not replaced by a cue word")
asked_keys.clear()
out, writes, used = use({}, lambda k: asked_keys.append(k), NOW, "Flights to Maui from SFO")
check(asked_keys == [], "table places and airport codes after a cue are not looked up")

# ── The step end to end ──────────────────────────────────────────────────
head, body_code = code.split("# ── The turn ", 1)
stored = {}


def step(text, vertex, firestore):
    calls.clear()
    seen = {"firestore": []}

    def urlopen(req, timeout=None):
        url = req.full_url
        if "metadata.google.internal" in url:
            return Resp({"access_token": "t"})
        if "firestore.googleapis.com" in url:
            seen["firestore"].append((url, timeout))
            return firestore(url)
        calls.append(url)
        nxt = vertex.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt
    g = {"thread_path": "chat_threads/chat-r1", "event_payload": {"text": text},
         "input_event": {"type": "user_message", "payload": {"text": text}},
         "loaded_state": {"found": False}, "relation_docs": [],
         "llm_enabled": True, "llm_model": "m", "vertex_project": "p", "vertex_region": "global",
         "today_override": TODAY.isoformat(), "firestore_project": "proj", "firestore_database": "(default)"}
    exec(head, g)
    g["urllib"].request.urlopen = urlopen
    g["time"].sleep = lambda s: None
    exec("# ── The turn " + body_code, g)
    return g["result"], seen


def napa_doc(url):
    if url.endswith("/intake_place_facts/napa"):
        return Resp({"fields": {"facts_json": {"stringValue": json.dumps(NAPA)}, "source": {"stringValue": "model"},
                                "expires_at": {"stringValue": "2999-01-01T00:00:00+00:00"}}})
    raise http_error(404)


r, seen = step("Flights to Napa from SFO", [TimeoutError("t"), TimeoutError("t")], napa_doc)
st = r["intake_state"]
check(r["llm"]["used"] is False and "TimeoutError" in r["llm"]["fallback_reason"], "the model timed out twice: the rule reader answered")
check(st.get("destination_options") and {"SFO", "OAK"} <= set(st["destination_options"]) and st.get("destination_nearest"),
      "...and the cached Napa still gives Napa's nearest airports (it was 'couldn't match' before)")
check(r["place_cache"]["used"] == ["napa"] and seen["firestore"][0][1] == 3, "the cache was read (3 s cap)")
check(not any(d["path"].startswith("intake_place_facts/") for d in r["turn_docs"]), "a cache hit stores nothing")

model_patch = {"intent": "flight", "destination": {"text": "Carmel-by-the-Sea", "kind": "city", "lat": 36.555, "lon": -121.923, "airports": []},
               "origin": {"text": "SFO", "kind": "airport"}}
r, seen = step("Flights to Carmel-by-the-Sea from SFO", [vertex_ok(model_patch)], lambda url: (_ for _ in ()).throw(http_error(404)))
docs = [d for d in r["turn_docs"] if d["path"].startswith("intake_place_facts/")]
check(r["llm"]["used"] and len(docs) == 1 and docs[0]["path"] == "intake_place_facts/carmel-by-the-sea"
      and r["place_cache"]["stored"] == ["carmel-by-the-sea"], "a new place the model read is stored, in the turn's own save")
check(r["turn_docs"][0]["path"].endswith("/slot_state/intake"), "the turn's own documents come first, as before")
r, seen = step("Flights to Carmel-by-the-Sea from SFO", [vertex_ok(model_patch)], lambda url: (_ for _ in ()).throw(OSError("down")))
check(r["llm"]["used"] and r["intake_state"].get("destination_options"), "Firestore down: the turn goes on, uncached")

if failures:
    sys.exit("%d failure(s)" % len(failures))
