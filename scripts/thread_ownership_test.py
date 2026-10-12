#!/usr/bin/env python3
"""Thread access and the user<->thread relation, run against the real step code.

Executes the embedded `code:` of
  - itinerary-planner `load_slot_state` (ownership decision + index writes),
  - itinerary-planner `refuse_thread`,
  - threads `run` (list / participants / rename / archive / unarchive / unlink),
against an in-memory Firestore behind a patched `urllib.request.urlopen`, so
the HTTP the steps would send is what is asserted. No network.

The planner checks are the security property: a session can never load or write
a thread it does not own, and chat_threads/** is never written by these steps.
"""
import hashlib
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
        if url == ROOT.rstrip("/") + ":runQuery":
            url = ROOT + ":runQuery"  # a query over the whole database
        assert url.startswith(ROOT), url
        rest = url[len(ROOT):]
        path, _, query = rest.partition("?")
        if path.endswith(":runQuery"):
            parent = urllib.parse.unquote(path[: -len(":runQuery")]).rstrip("/")
            q = json.loads(req.data)["structuredQuery"]
            coll = q["from"][0]["collectionId"]
            prefix = (parent + "/" if parent else "") + coll + "/"
            flt = (q.get("where") or {}).get("fieldFilter")
            rows = []
            for k, v in self.docs.items():
                if not k.startswith(prefix) or "/" in k[len(prefix):]:
                    continue
                if flt and v.get(flt["field"]["fieldPath"]) != dec(flt["value"]):
                    continue
                rows.append({"document": {"name": "x/" + k, "fields": {f: enc(x) for f, x in v.items()}}})
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


def edge_id(uid, tid):
    return hashlib.sha256((uid + "\n" + tid).encode()).hexdigest()


def edge_path(uid, tid):
    return "user_thread_map/" + edge_id(uid, tid)


def paths(r):
    return [d["path"] for d in r["relation_docs"]]


def edge(uid, tid, role="owner", **kw):
    d = {"uid": uid, "thread_id": tid, "role": role, "label": "L", "turn_count": 1,
         "first_added_at_ms": 1, "last_activity_ms": 1, "archived": False}
    d.update(kw)
    return d


# ── bindings the step code needs are the ones the playbook supplies ──
for name in ("thread_id", "user_uid", "event_type", "event_payload", "allow_guest_threads"):
    check(name in (LOAD_STEP["tool"].get("input") or {}), "load_slot_state binds %s" % name)
arcs = LOAD_STEP["next"]["arcs"]
check(arcs[0].get("step") == "extract_turn" and "thread_access.ok" in arcs[0].get("when", ""),
      "extract_turn is reached only when thread_access.ok")
check(arcs[-1] == {"step": "refuse_thread"}, "everything else goes to refuse_thread")
for path in (PLANNER, THREADS, "scripts/backfill_user_thread_map.py"):
    check('"\\n"' in open(path).read() or '"\n"' in open(path).read(), "edge id hashes uid + newline + thread_id in %s" % path)

# ── first access: a brand-new thread makes its first user the owner ──
fs = FakeFirestore()
r = load(fs)
check(r["thread_access"]["ok"] and r["thread_access"]["claim"] and r["thread_access"]["role"] == "owner",
      "new thread: allowed, caller becomes owner")
check(paths(r) == [edge_path(ALICE, "t1"), "thread_owners/t1"], "new thread: edge + owner record queued")
e = r["relation_docs"][0]
check(e["merge"] and e["doc"]["uid"] == ALICE and e["doc"]["thread_id"] == "t1" and e["doc"]["role"] == "owner"
      and e["doc"]["label"] == "Paris in May" and e["doc"]["turn_count"] == 1, "new edge: uid, thread_id, role, label")
check(not fs.writes, "load_slot_state itself writes nothing")
check(all(not p.startswith("chat_threads/") for p in paths(r)), "no relation write touches chat_threads/**")

# ── the owner continues; a stranger who posts is refused and gets NO edge ──
owned = {
    SLOT: {"region": "Paris"},
    "thread_owners/t1": {"uid": ALICE, "created_at_ms": 1000},
    edge_path(ALICE, "t1"): edge(ALICE, "t1", label="My trip", turn_count=4),
}
r = load(FakeFirestore(owned))
check(r["thread_access"]["ok"] and r["thread_access"]["reason"] == "member" and not r["thread_access"]["claim"],
      "owner with edge: allowed, no re-claim")
doc = r["relation_docs"][0]["doc"]
check(paths(r) == [edge_path(ALICE, "t1")] and doc["turn_count"] == 5 and "label" not in doc
      and "role" not in doc and "archived" not in doc, "owner: turn_count increments; label/role/archive untouched")

r = load(FakeFirestore(owned), uid=BOB)
check(not r["thread_access"]["ok"] and r["thread_access"]["reason"] == "not_member", "stranger posting: refused")
check(r["relation_docs"] == [], "stranger posting: no edge is created (no join-by-posting)")

# ── an existing member (granted out of band) is allowed ──
shared = dict(owned, **{edge_path(BOB, "t1"): edge(BOB, "t1", role="member")})
r = load(FakeFirestore(shared), uid=BOB)
check(r["thread_access"]["ok"] and r["thread_access"]["role"] == "member", "member with an edge: allowed")

# ── a forged edge (fields not matching its id) grants nothing ──
forged = dict(owned, **{edge_path(BOB, "t1"): edge(ALICE, "t1")})
check(load(FakeFirestore(forged), uid=BOB)["thread_access"]["reason"] == "not_member", "mismatched edge grants nothing")

# ── owner edge lost: repaired from the owner record ──
r = load(FakeFirestore({SLOT: {"r": 1}, "thread_owners/t1": {"uid": ALICE, "created_at_ms": 1000}}))
check(r["thread_access"]["reason"] == "owner_edge_repaired" and r["relation_docs"][0]["doc"]["role"] == "owner"
      and r["relation_docs"][0]["doc"]["first_added_at_ms"] == 1000, "owner without edge: edge repaired")

# ── fail closed ──
r = load(FakeFirestore({SLOT: {"region": "Paris"}}))
check(r["thread_access"]["reason"] == "unclaimed_history" and r["relation_docs"] == [],
      "history with no owner: refused, not claimed")
r = load(FakeFirestore({SLOT: {"r": 1}, "thread_owners/t1": {"uid": ALICE, "unlinked_at_ms": 5}}))
check(r["thread_access"]["reason"] == "thread_unlinked", "owner who unlinked: refused")
r = load(FakeFirestore(owned, fail_paths={edge_path(ALICE, "t1")}))
check(r["thread_access"]["reason"] == "access_unverifiable", "edge lookup failure: refused")
r = load(FakeFirestore(owned, fail_paths={"thread_owners/t1"}), uid=BOB)
check(r["thread_access"]["reason"] == "access_unverifiable", "owner lookup failure: refused")
r = load(FakeFirestore(owned, fail_paths={SLOT}))
check(r["thread_access"]["reason"] == "access_unverifiable", "slot lookup failure: refused")
for bad in ("../t1", "a/b", "", "x" * 129, "t 1"):
    check(load(FakeFirestore(), thread_id=bad)["thread_access"]["reason"] == "invalid_thread_id",
          "invalid thread id refused: %r" % bad[:12])
check(load(FakeFirestore(), uid="auth0|a/x")["thread_access"]["reason"] == "invalid_uid", "uid with a slash refused")

# ── anonymous callers ──
check(load(FakeFirestore(), uid="guest")["thread_access"]["reason"] == "sign_in_required", "guest: refused")
check(load(FakeFirestore(owned), uid="")["thread_access"]["reason"] == "sign_in_required",
      "no uid cannot reach an owned thread")
r = load(FakeFirestore(), thread_id="_smoke-abc", uid="guest")
check(r["thread_access"]["ok"] and r["relation_docs"] == [], "guest on a _smoke- thread: allowed, not mapped")
check(load(FakeFirestore(), uid="guest", allow_guest=True)["thread_access"]["ok"], "allow_guest_threads opts in")

# ── refuse_thread reveals nothing ──
r = run_code(REFUSE_CODE, {"access": {"ok": False, "reason": "not_member"}, "request_id": "", "gateway_url": ""}, FakeFirestore())
check(r["thread_access"] == "denied" and r["thread_access_reason"] == "unavailable"
      and r["final_slot_state"] == {}, "refusal: 'not yours' reads as unavailable, with no thread data")

# ── management playbook ──
def threads(fs, **kw):
    b = {"uid": ALICE, "action": "list", "thread_id": "", "label": "", "include_archived": False,
         "limit": 50, "request_id": "", "gateway_url": "", "firestore_project": PROJECT,
         "firestore_database": "(default)"}
    b.update(kw)
    return run_code(THREADS_CODE, b, fs)


def relation():
    return {
        "thread_owners/t1": {"uid": ALICE}, "thread_owners/t2": {"uid": ALICE}, "thread_owners/t3": {"uid": BOB},
        edge_path(ALICE, "t1"): edge(ALICE, "t1", label="A", last_activity_ms=10),
        edge_path(ALICE, "t2"): edge(ALICE, "t2", label="B", last_activity_ms=20, archived=True),
        edge_path(BOB, "t3"): edge(BOB, "t3", label="Bob's", last_activity_ms=30),
        edge_path(BOB, "t1"): edge(BOB, "t1", role="member", first_added_at_ms=5),
        "chat_threads/t1/slot_state/current": {"region": "Paris"},
    }


for name in ("uid", "action", "thread_id", "label"):
    check(name in (THREADS_STEP["tool"].get("input") or {}), "threads binds %s" % name)
r = threads(FakeFirestore(relation()))
check([t["thread_id"] for t in r["threads"]] == ["t1"], "list: the caller's threads only, archived hidden")
r = threads(FakeFirestore(relation()), include_archived=True)
check([t["thread_id"] for t in r["threads"]] == ["t2", "t1"], "list: archived on request, newest first")
check([t["thread_id"] for t in threads(FakeFirestore(relation()), uid=BOB)["threads"]] == ["t3", "t1"],
      "list: many-to-many -- a member sees the shared thread too")

r = threads(FakeFirestore(relation()), action="participants", thread_id="t1")
check([(p["uid"], p["role"]) for p in r["participants"]] == [(ALICE, "owner"), (BOB, "member")],
      "participants: all users of a thread")
check(threads(FakeFirestore(relation()), action="participants", thread_id="t3").get("error") == "thread_not_found",
      "participants: refused for a thread the caller is not in")

fs = FakeFirestore(relation())
threads(fs, action="rename", thread_id="t1", label="  Summer   in Paris ")
check(fs.docs[edge_path(ALICE, "t1")]["label"] == "Summer in Paris" and fs.docs[edge_path(BOB, "t1")]["label"] == "L",
      "rename: only the caller's own label")
threads(fs, action="archive", thread_id="t1")
check(fs.docs[edge_path(ALICE, "t1")]["archived"] is True, "archive")
threads(fs, action="unarchive", thread_id="t1")
check(fs.docs[edge_path(ALICE, "t1")]["archived"] is False, "unarchive")

fs = FakeFirestore(relation())
r = threads(fs, uid=BOB, action="unlink", thread_id="t1")
check(r["role"] == "member" and edge_path(BOB, "t1") not in fs.docs
      and not fs.docs["thread_owners/t1"].get("unlinked_at_ms"), "member unlink: only their edge goes")
check(load(fs, uid=BOB)["thread_access"]["reason"] == "not_member", "member unlink: access ends")
check(load(fs)["thread_access"]["ok"], "member unlink: the owner is unaffected")

fs = FakeFirestore(relation())
r = threads(fs, action="unlink", thread_id="t1")
check(r["role"] == "owner" and edge_path(ALICE, "t1") not in fs.docs and fs.docs["thread_owners/t1"].get("unlinked_at_ms"),
      "owner unlink: edge removed, owner record marked unlinked")
check("chat_threads/t1/slot_state/current" in fs.docs
      and all(not w[1].startswith("chat_threads/") for w in fs.writes), "unlink: chat_threads/** kept (no GC)")
check(load(fs)["thread_access"]["reason"] == "thread_unlinked", "owner unlink: the planner then refuses it")

fs = FakeFirestore(relation())
for act in ("rename", "archive", "unlink"):
    check(threads(fs, action=act, thread_id="t3", label="mine").get("error") == "thread_not_found",
          "%s a thread the caller is not in: not found" % act)
check(not fs.writes, "nothing written for a thread the caller is not in")
for u in ("", "guest", "a/b"):
    check(threads(FakeFirestore(relation()), uid=u).get("error") == "sign_in_required", "threads refuses uid %r" % u)
check(threads(FakeFirestore(relation()), action="rename", thread_id="../x").get("error") == "invalid_thread_id",
      "threads refuses an invalid thread id")
check(threads(FakeFirestore(relation()), action="delete").get("error") == "unknown_action", "unknown action refused")

print("---")
print("failures: %d" % len(failures))
sys.exit(1 if failures else 0)
