#!/usr/bin/env python3
"""Thread ownership and the per-user thread index, run against the real step code.

Executes the embedded `code:` of
  - itinerary-planner `load_slot_state` (ownership decision + index writes),
  - itinerary-planner `refuse_thread`,
  - threads `run` (list / rename / archive / unarchive / delete),
against an in-memory Firestore behind a patched `urllib.request.urlopen`, so
the HTTP the steps would send is what is asserted. No network.

The planner checks are the security property: a session can never load or write
a thread it does not own, and chat_threads/** is never written by these steps.
"""
import io
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

import yaml

PLANNER = "playbooks/itinerary-planner.yaml"
THREADS = "playbooks/threads.yaml"
PROJECT = "test-project"
ROOT = "https://firestore.googleapis.com/v1/projects/%s/databases/(default)/documents/" % PROJECT

failures = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


def step_code(path, name):
    doc = yaml.safe_load(open(path))
    step = next(s for s in doc["workflow"] if s.get("step") == name)
    return step["tool"]["code"], step


def enc(v):
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, dict):
        return {"mapValue": {"fields": {k: enc(x) for k, x in v.items()}}}
    return {"stringValue": str(v)}


def dec(v):
    if "booleanValue" in v:
        return v["booleanValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "stringValue" in v:
        return v["stringValue"]
    if "nullValue" in v:
        return None
    if "mapValue" in v:
        return {k: dec(x) for k, x in v["mapValue"].get("fields", {}).items()}
    return v


class FakeFirestore:
    """Documents keyed by relative path; records every write."""

    def __init__(self, docs=None, fail_paths=()):
        self.docs = {k: dict(v) for k, v in (docs or {}).items()}
        self.writes = []
        self.fail_paths = set(fail_paths)

    def urlopen(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        method = req.get_method()
        if "metadata.google.internal" in url:
            return _resp({"access_token": "t"})
        assert url.startswith(ROOT), url
        rest = url[len(ROOT):]
        path, _, query = rest.partition("?")
        if path.endswith(":runQuery"):
            parent = urllib.parse.unquote(path[: -len(":runQuery")])
            q = json.loads(req.data)["structuredQuery"]
            coll = q["from"][0]["collectionId"]
            prefix = parent + "/" + coll + "/"
            rows = [
                {"document": {"name": "x/" + k, "fields": {f: enc(x) for f, x in v.items()}}}
                for k, v in self.docs.items()
                if k.startswith(prefix) and "/" not in k[len(prefix):]
            ]
            rows.sort(key=lambda r: -int(r["document"]["fields"].get("last_activity_ms", {"integerValue": "0"})["integerValue"]))
            return _resp(rows[: q.get("limit", 50)])
        path = urllib.parse.unquote(path)
        if path in self.fail_paths:
            raise urllib.error.HTTPError(url, 500, "boom", {}, io.BytesIO(b"{}"))
        if method == "GET":
            if path not in self.docs:
                raise urllib.error.HTTPError(url, 404, "nf", {}, io.BytesIO(b"{}"))
            return _resp({"name": "projects/p/databases/d/documents/" + path,
                          "fields": {k: enc(v) for k, v in self.docs[path].items()}})
        if method == "PATCH":
            fields = {k: dec(v) for k, v in json.loads(req.data)["fields"].items()}
            self.writes.append(("PATCH", path, fields))
            self.docs.setdefault(path, {}).update(fields)
            return _resp({})
        if method == "DELETE":
            self.writes.append(("DELETE", path, None))
            self.docs.pop(path, None)
            return _resp({})
        raise AssertionError("unexpected %s %s" % (method, url))


class _resp(io.BytesIO):
    def __init__(self, payload, status=200):
        super().__init__(json.dumps(payload).encode())
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def run_code(code, bindings, fs):
    real = urllib.request.urlopen
    urllib.request.urlopen = fs.urlopen
    try:
        g = dict(bindings)
        exec(code, g)
        return g["result"]
    finally:
        urllib.request.urlopen = real


LOAD_CODE, LOAD_STEP = step_code(PLANNER, "load_slot_state")
REFUSE_CODE, _ = step_code(PLANNER, "refuse_thread")
THREADS_CODE, THREADS_STEP = step_code(THREADS, "run")

ALICE, BOB = "auth0|alice", "auth0|bob"
SLOT = "chat_threads/t1/slot_state/current"


def load(fs, thread_id="t1", uid=ALICE, text="Paris in May", allow_guest=False):
    return run_code(LOAD_CODE, {
        "doc_path": "chat_threads/%s/slot_state/current" % thread_id,
        "firestore_database": "(default)",
        "firestore_project": PROJECT,
        "thread_id": thread_id,
        "user_uid": uid,
        "event_type": "user_message",
        "event_payload": {"text": text},
        "allow_guest_threads": allow_guest,
    }, fs)


def paths(r):
    return [d["path"] for d in r["index_docs"]]


# ── bindings the step code needs are the ones the playbook supplies ──
for name in ("thread_id", "user_uid", "event_type", "event_payload", "allow_guest_threads"):
    check(name in (LOAD_STEP["tool"].get("input") or {}), "load_slot_state binds %s" % name)
arcs = LOAD_STEP["next"]["arcs"]
check(arcs[0].get("step") == "extract_turn" and "thread_access.ok" in arcs[0].get("when", ""),
      "extract_turn is reached only when thread_access.ok")
check(arcs[-1] == {"step": "refuse_thread"}, "everything else goes to refuse_thread")

# ── a brand-new thread is claimed by its first user ──
fs = FakeFirestore()
r = load(fs)
check(r["thread_access"]["ok"] and r["thread_access"]["claim"], "new thread: allowed and claimed")
check(paths(r) == ["users/%s/threads/t1" % ALICE, "thread_owners/t1"], "new thread: pointer + owner record queued")
ptr = r["index_docs"][0]
check(ptr["merge"] and ptr["doc"]["title"] == "Paris in May" and ptr["doc"]["turn_count"] == 1
      and ptr["doc"]["archived"] is False, "new pointer: title from the first message, turn_count 1")
check(r["index_docs"][1]["doc"]["uid"] == ALICE, "owner record names the caller")
check(not fs.writes, "load_slot_state itself writes nothing")
check(all(not p.startswith("chat_threads/") for p in paths(r)), "no index write touches chat_threads/**")

# ── the owner continues; someone else is refused ──
owned = {
    SLOT: {"region": "Paris"},
    "thread_owners/t1": {"uid": ALICE, "created_at_ms": 1000},
    "users/%s/threads/t1" % ALICE: {"thread_id": "t1", "title": "My trip", "turn_count": 4},
}
r = load(FakeFirestore(owned))
check(r["thread_access"]["ok"] and not r["thread_access"]["claim"], "owner: allowed, no re-claim")
check(paths(r) == ["users/%s/threads/t1" % ALICE], "owner: only the pointer is updated")
doc = r["index_docs"][0]["doc"]
check(doc["turn_count"] == 5 and "title" not in doc and "archived" not in doc,
      "owner: turn_count increments; a renamed title and archive flag are left alone")

r = load(FakeFirestore(owned), uid=BOB)
check(not r["thread_access"]["ok"] and r["thread_access"]["reason"] == "not_owner", "another user: refused")
check(r["index_docs"] == [], "another user: nothing queued")

# ── fail closed ──
r = load(FakeFirestore({SLOT: {"region": "Paris"}}))
check(r["thread_access"]["reason"] == "unclaimed_history", "history with no owner: refused, not claimed")
r = load(FakeFirestore(dict(owned, **{"thread_owners/t1": {"uid": ALICE, "unlinked_at_ms": 5}})))
check(r["thread_access"]["reason"] == "thread_deleted", "deleted (unlinked) thread: refused")
r = load(FakeFirestore(owned, fail_paths={"thread_owners/t1"}))
check(r["thread_access"]["reason"] == "ownership_unverifiable", "owner lookup failure: refused")
r = load(FakeFirestore(owned, fail_paths={SLOT}))
check(r["thread_access"]["reason"] == "ownership_unverifiable", "slot lookup failure: refused")
for bad in ("../t1", "a/b", "", "x" * 129, "t 1"):
    check(load(FakeFirestore(), thread_id=bad)["thread_access"]["reason"] == "invalid_thread_id",
          "invalid thread id refused: %r" % bad[:12])
check(load(FakeFirestore(), uid="auth0|a/threads/x")["thread_access"]["reason"] == "invalid_uid",
      "uid with a slash refused")

# ── anonymous callers ──
check(load(FakeFirestore(), uid="guest")["thread_access"]["reason"] == "sign_in_required", "guest: refused")
check(load(FakeFirestore(owned), uid="")["thread_access"]["reason"] == "sign_in_required",
      "no uid cannot reach an owned thread")
r = load(FakeFirestore(), thread_id="_smoke-abc", uid="guest")
check(r["thread_access"]["ok"] and r["index_docs"] == [], "guest on a _smoke- thread: allowed, not indexed")
check(load(FakeFirestore(), uid="guest", allow_guest=True)["thread_access"]["ok"], "allow_guest_threads opts in")

# ── refuse_thread reveals nothing ──
r = run_code(REFUSE_CODE, {"access": {"ok": False, "reason": "not_owner"}, "request_id": "", "gateway_url": ""}, FakeFirestore())
check(r["thread_access"] == "denied" and r["thread_access_reason"] == "unavailable"
      and r["final_slot_state"] == {}, "refusal: 'not yours' reads as unavailable, with no thread data")

# ── management playbook ──
def threads(fs, **kw):
    b = {"uid": ALICE, "action": "list", "thread_id": "", "title": "", "include_archived": False,
         "limit": 50, "request_id": "", "gateway_url": "", "firestore_project": PROJECT,
         "firestore_database": "(default)"}
    b.update(kw)
    return run_code(THREADS_CODE, b, fs)


def index():
    return {
        "thread_owners/t1": {"uid": ALICE}, "thread_owners/t2": {"uid": ALICE},
        "thread_owners/t3": {"uid": BOB},
        "users/%s/threads/t1" % ALICE: {"thread_id": "t1", "title": "A", "last_activity_ms": 10},
        "users/%s/threads/t2" % ALICE: {"thread_id": "t2", "title": "B", "last_activity_ms": 20, "archived": True},
        "users/%s/threads/t3" % BOB: {"thread_id": "t3", "title": "Bob's", "last_activity_ms": 30},
        "chat_threads/t1/slot_state/current": {"region": "Paris"},
    }


for name in ("uid", "action", "thread_id", "title"):
    check(name in (THREADS_STEP["tool"].get("input") or {}), "threads binds %s" % name)
r = threads(FakeFirestore(index()))
check([t["thread_id"] for t in r["threads"]] == ["t1"], "list: own threads only, archived hidden")
r = threads(FakeFirestore(index()), include_archived=True)
check([t["thread_id"] for t in r["threads"]] == ["t2", "t1"], "list: archived included on request, newest first")

fs = FakeFirestore(index())
r = threads(fs, action="rename", thread_id="t1", title="  Summer   in Paris ")
check(r["status"] == "ok" and fs.docs["users/%s/threads/t1" % ALICE]["title"] == "Summer in Paris", "rename")
r = threads(fs, action="archive", thread_id="t1")
check(fs.docs["users/%s/threads/t1" % ALICE]["archived"] is True, "archive")
r = threads(fs, action="unarchive", thread_id="t1")
check(fs.docs["users/%s/threads/t1" % ALICE]["archived"] is False, "unarchive")

fs = FakeFirestore(index())
r = threads(fs, action="delete", thread_id="t1")
check(r["mode"] == "unlinked" and "users/%s/threads/t1" % ALICE not in fs.docs, "delete: pointer removed")
check(fs.docs["thread_owners/t1"].get("unlinked_at_ms"), "delete: owner record marked unlinked")
check("chat_threads/t1/slot_state/current" in fs.docs
      and all(not w[1].startswith("chat_threads/") for w in fs.writes), "delete: chat_threads/** kept")
check(load(fs)["thread_access"]["reason"] == "thread_deleted", "delete: the planner then refuses the thread")

fs = FakeFirestore(index())
for act in ("rename", "archive", "delete"):
    r = threads(fs, action=act, thread_id="t3", title="mine now")
    check(r.get("error") == "thread_not_found", "%s someone else's thread: not found" % act)
check(not fs.writes, "nothing written for another user's thread")
fs = FakeFirestore(dict(index(), **{"users/%s/threads/t3" % ALICE: {"thread_id": "t3"}}))
check(threads(fs, action="rename", thread_id="t3", title="x").get("error") == "thread_not_found",
      "a forged pointer to someone else's thread does not grant it")
for uid in ("", "guest", "a/b"):
    check(threads(FakeFirestore(index()), uid=uid).get("error") == "sign_in_required", "threads refuses uid %r" % uid)
check(threads(FakeFirestore(index()), action="rename", thread_id="../x").get("error") == "invalid_thread_id",
      "threads refuses an invalid thread id")
check(threads(FakeFirestore(index()), action="purge").get("error") == "unknown_action", "unknown action refused")

print("---")
print("failures: %d" % len(failures))
sys.exit(1 if failures else 0)
