#!/usr/bin/env python3
"""Validate what an itinerary-planner chat turn actually stored in Firestore.  READ-ONLY.

For each turn (one `muno/playbooks/itinerary-planner` execution) this compares
what the execution record says the turn SHOULD have written with what is really
in Firestore:

  expected (from the NoETL execution record)        actual (Firestore, live project)
  ------------------------------------------        --------------------------------
  extract_turn.turn_events + render post_events  ->  chat_threads/{tid}/events/*   (types, in order)
  extract_turn.turn_docs + render post_docs      ->  slot_state/current, api_calls/{call_id},
    (incl. #148 relation docs)                        user_thread_map/{edge}, thread_owners/{tid}
  the async persist child (mcp/firestore)        ->  its set/append counts vs the expected counts

Checks (PASS / FAIL / INFO per turn):
  identity      workload user_uid is a real Auth0 subject, not "guest"/empty
  access        load_slot_state granted the turn (owner/member) for that uid
  persist       the persist child COMPLETED and wrote every doc/event the turn produced
  events        this turn's event types are in Firestore, in order, after the previous turn
  seq           the thread's seq is unique and contiguous 1..N
  docs          slot_state/current and every expected api_calls/{id} document exist
  owner         thread_owners/{tid}.uid == the turn's user
  edge          user_thread_map/{sha256(uid+"\\n"+tid)} exists, uid/thread_id match, role owner,
                and its last_activity_ms covers this turn (catches lost relation updates)
  actor         INFO: Firestore events do not store `actor` (the provider persists only
                seq/type/payload/thread_path/server_time), so per-event user attribution is
                via thread_owners / user_thread_map, not the event.

Usage (needs gcloud auth with read access to Firestore, and a NoETL server API, e.g. a
port-forward: kubectl -n noetl port-forward pod/noetl-server-rust-embedded-0 47382:8082):

  python3 scripts/validate_turn_firestore.py --execution 369136021201231872
  python3 scripts/validate_turn_firestore.py --thread chat-mv9nsqro-6lnikf
  python3 scripts/validate_turn_firestore.py --since-minutes 60
  [--server http://localhost:47382] [--project shastaratech-noetl-prod] [--json]

Exit code: 0 when every check passes, 1 if any check fails.
"""
import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

PLANNER = "muno/playbooks/itinerary-planner"
ANONYMOUS = ("", "guest", None)


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _get(url, headers=None, data=None, timeout=60):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


class Noetl:
    def __init__(self, base):
        self.base = base.rstrip("/")

    def execution(self, eid):
        return _get(f"{self.base}/api/executions/{eid}")

    def recent(self, limit=200):
        q = urllib.parse.urlencode({"limit": limit, "path": PLANNER})
        return _get(f"{self.base}/api/executions?{q}") or []


class Firestore:
    def __init__(self, project, database="(default)"):
        self.project = project
        self.root = (f"https://firestore.googleapis.com/v1/projects/{project}/databases/"
                     f"{urllib.parse.quote(database, safe='()')}/documents")
        token = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
        self.h = {"Authorization": f"Bearer {token}", "x-goog-user-project": project,
                  "Content-Type": "application/json"}

    @staticmethod
    def decode(v):
        if not isinstance(v, dict):
            return v
        for k in ("stringValue", "booleanValue", "timestampValue"):
            if k in v:
                return v[k]
        if "integerValue" in v:
            return int(v["integerValue"])
        if "doubleValue" in v:
            return float(v["doubleValue"])
        if "nullValue" in v:
            return None
        if "mapValue" in v:
            return {k: Firestore.decode(x) for k, x in v["mapValue"].get("fields", {}).items()}
        if "arrayValue" in v:
            return [Firestore.decode(x) for x in v["arrayValue"].get("values", [])]
        return v

    def doc(self, path):
        d = _get(f"{self.root}/{urllib.parse.quote(path, safe='/')}", self.h)
        return None if d is None else {k: self.decode(v) for k, v in d.get("fields", {}).items()}

    def events(self, thread_id):
        q = {"structuredQuery": {"from": [{"collectionId": "events"}],
                                 "orderBy": [{"field": {"fieldPath": "seq"}, "direction": "ASCENDING"}]}}
        rows = _get(f"{self.root}/chat_threads/{urllib.parse.quote(thread_id)}:runQuery", self.h,
                    json.dumps(q).encode()) or []
        return [{k: self.decode(v) for k, v in r["document"].get("fields", {}).items()} for r in rows if "document" in r]


# ── reading the execution record ──────────────────────────────────────────────

def step_data(ex, node):
    for e in ex.get("events", []):
        if e.get("node_name") == node and e.get("event_type") == "call.done":
            try:
                return e["result"]["context"]["result"]["context"]["data"]
            except (KeyError, TypeError):
                return None
    return None


def persist_child_id(ex):
    for e in ex.get("events", []):
        if e.get("node_name") == "persist_all_atomically" and e.get("event_type") == "call.done":
            ctx = (((e.get("result") or {}).get("context") or {}).get("result") or {}).get("context") or {}
            return ctx.get("child_execution_id") or (ctx.get("data") or {}).get("execution_id")
    return None


def find_counts(obj):
    if isinstance(obj, dict):
        if "set_count" in obj and "event_count" in obj:
            return obj
        for v in obj.values():
            r = find_counts(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_counts(v)
            if r:
                return r
    return None


def ms(ts):
    return int(dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000) if ts else 0


def ts_ms(v):
    if isinstance(v, (int, float)):
        return int(v)
    try:
        return ms(v)
    except (TypeError, ValueError):
        return 0


def locate_turn(types, times_ms, expected, start, turn_ms):
    """Where a turn's events sit in the thread, and how much of the expected sequence is stored.

    Events are appended in turn order, so the turn opens at the first event at/after `start`
    whose type is the turn's first expected type and that was written after the turn started;
    from there, count how many of the expected types follow in order. Returns (index, stored).
    """
    opens = [i for i in range(start, len(types)) if expected and types[i] == expected[0]]
    i0 = next((i for i in opens if times_ms[i] >= turn_ms), opens[0] if opens else None)
    if i0 is None:
        return None, []
    n = 0
    while n < len(expected) and i0 + n < len(types) and types[i0 + n] == expected[n]:
        n += 1
    return i0, types[i0:i0 + n]


def edge_id(uid, tid):
    return hashlib.sha256((uid + "\n" + tid).encode()).hexdigest()


# ── one turn ──────────────────────────────────────────────────────────────────

def validate(noetl, fs, eid, thread_events_cache, prior_turns):
    ex = noetl.execution(eid)
    R = {"execution_id": str(eid), "checks": {}, "retrieved": {}}
    C = R["checks"]

    def put(name, ok, detail):
        C[name] = {"result": ("PASS" if ok else "FAIL") if ok is not None else "INFO", "detail": detail}

    if not ex:
        put("execution", False, "not found on the NoETL server")
        return R
    wl = ex.get("workload") or {}
    tid = str(wl.get("thread_id") or "")
    tid = tid.split("/", 1)[1] if tid.startswith("chat_threads/") else tid
    uid = wl.get("user_uid")
    R.update(thread_id=tid, status=ex.get("status"), started_at=ex.get("started_at"))
    R["retrieved"]["user"] = (uid or "")[:12] + ("…" if uid and len(uid) > 12 else "")

    access = (step_data(ex, "load_slot_state") or {}).get("thread_access") or {}
    if uid in ANONYMOUS:
        # A guest turn is expected to be refused before anything is written.
        put("identity", None, "user_uid=(guest/empty): anonymous turn")
        put("access", not access.get("ok"), f"{access.get('reason')}: "
            + ("refused as expected, nothing to store" if not access.get("ok") else "an anonymous turn was GRANTED"))
        return R
    put("identity", True, "user_uid=auth0 subject")
    put("access", bool(access.get("ok")), f"{access.get('reason')}/{access.get('role')}")
    if not access.get("ok"):
        put("persist", None, "turn refused by thread access; nothing should be written")
        return R

    ext = step_data(ex, "extract_turn") or {}
    ren = step_data(ex, "render_widget_chat") or {}
    exp_events = [e.get("event", {}).get("type") for e in (ext.get("turn_events") or [])] + \
                 [e.get("event", {}).get("type") for e in (ren.get("post_events") or [])]
    exp_docs = [d.get("path") for d in (ext.get("turn_docs") or [])] + [d.get("path") for d in (ren.get("post_docs") or [])]
    R["retrieved"]["expected_event_types"] = exp_events
    R["retrieved"]["expected_doc_paths"] = exp_docs

    child = persist_child_id(ex)
    cex = noetl.execution(child) if child else None
    counts = find_counts(cex) if cex else None
    if not counts:
        put("persist", False, f"persist child {child} has no write counts (status {cex and cex.get('status')})")
    else:
        ok = (cex.get("status") == "COMPLETED" and counts["set_succeeded"] == counts["set_count"] == len(exp_docs)
              and counts["event_succeeded"] == counts["event_count"] == len(exp_events))
        put("persist", ok, f"child {child} {cex.get('status')}: docs {counts['set_succeeded']}/{counts['set_count']} "
                           f"(turn produced {len(exp_docs)}), events {counts['event_succeeded']}/{counts['event_count']} "
                           f"(turn produced {len(exp_events)})")

    if tid not in thread_events_cache:
        thread_events_cache[tid] = fs.events(tid)
    evs = thread_events_cache[tid]
    seqs = [e.get("seq") for e in evs]
    put("seq", seqs == list(range(1, len(seqs) + 1)), f"{len(seqs)} events, seq 1..{len(seqs)} " +
        ("contiguous" if seqs == list(range(1, len(seqs) + 1)) else f"BROKEN {seqs}"))

    # This turn's block: the first event at/after the thread's consumed offset whose type opens
    # the turn and which was written after the turn started (server_time), then as much of the
    # expected sequence as is actually stored there. Works for one execution or a whole thread.
    i0, block = locate_turn([e.get("type") for e in evs], [ts_ms(e.get("server_time")) for e in evs],
                            exp_events, prior_turns.get(tid, 0), ms(ex.get("started_at")))
    prior_turns[tid] = (i0 + len(block)) if i0 is not None else prior_turns.get(tid, 0)
    n = len(block)
    R["retrieved"]["stored_event_types"] = block
    where = f"seq {i0 + 1}..{i0 + n}" if n else "nothing"
    put("events", block == exp_events and bool(exp_events),
        f"stored {len(block)}/{len(exp_events)} at {where}: {block}"
        + ("" if block == exp_events else f"; missing {exp_events[len(block):]}"))

    slot = fs.doc(f"chat_threads/{tid}/slot_state/current")
    calls = [p for p in exp_docs if "/api_calls/" in (p or "")]
    missing = [p for p in calls if fs.doc(p) is None]
    R["retrieved"]["slot_state_keys"] = sorted(slot.keys())[:8] if slot else None
    put("docs", slot is not None and not missing,
        f"slot_state/current {'present' if slot else 'MISSING'}; api_calls {len(calls) - len(missing)}/{len(calls)}"
        + (f" missing {missing}" if missing else ""))

    owner = fs.doc(f"thread_owners/{tid}")
    put("owner", bool(owner) and owner.get("uid") == uid, "thread_owners uid " +
        ("matches the turn's user" if owner and owner.get("uid") == uid else f"MISMATCH/absent ({owner and 'other uid'})"))

    edge = fs.doc(f"user_thread_map/{edge_id(uid or '', tid)}") if uid not in ANONYMOUS else None
    if not edge:
        put("edge", False, "user_thread_map edge absent")
    else:
        turn_ms = ms(ex.get("started_at"))
        fresh = (edge.get("last_activity_ms") or 0) >= turn_ms
        ok = edge.get("uid") == uid and edge.get("thread_id") == tid and edge.get("role") == "owner" and fresh
        put("edge", ok, f"role={edge.get('role')} turn_count={edge.get('turn_count')} last_activity "
                        + ("covers this turn" if fresh else "is OLDER than this turn (update lost)"))

    put("actor", None, "events in Firestore carry no actor/uid (not persisted by mcp/firestore); "
                       "attribution is thread_owners + user_thread_map")
    return R


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--execution")
    g.add_argument("--thread")
    g.add_argument("--since-minutes", type=int)
    ap.add_argument("--server", default="http://localhost:47382")
    ap.add_argument("--project", default="shastaratech-noetl-prod")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    noetl, fs = Noetl(a.server), Firestore(a.project)
    if a.execution:
        ids = [a.execution]
    else:
        rows = sorted(noetl.recent(), key=lambda r: r.get("started_at") or "")
        if a.since_minutes:
            cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=a.since_minutes)
            ids = [r["execution_id"] for r in rows if ms(r.get("started_at")) >= cutoff.timestamp() * 1000]
        else:
            ids = []
            for r in rows:
                wl = (noetl.execution(r["execution_id"]) or {}).get("workload") or {}
                if str(wl.get("thread_id") or "").split("/")[-1] == a.thread:
                    ids.append(r["execution_id"])

    cache, prior = {}, {}
    results = [validate(noetl, fs, eid, cache, prior) for eid in ids]

    if a.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            print(f"\n== {r['execution_id']}  thread={r.get('thread_id')}  status={r.get('status')}  started={r.get('started_at')}")
            for k, v in r["checks"].items():
                print(f"   {v['result']:<5} {k:<9} {v['detail']}")
    failed = any(v["result"] == "FAIL" for r in results for v in r["checks"].values())
    print(f"\n{len(results)} turn(s) checked; {'FAILURES FOUND' if failed else 'all checks passed'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
