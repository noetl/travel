#!/usr/bin/env python3
"""Attribution rules of scripts/backfill_user_thread_map.py (pure functions, no network)."""
import hashlib
import sys

sys.path.insert(0, "scripts")
from backfill_user_thread_map import classify, edge_for, edge_id  # noqa: E402

failures = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


def ev(uid, seq, type_="user_message", text="", ts=0):
    return {"actor": {"kind": "user", "uid": uid}, "seq": seq, "type": type_,
            "payload": {"text": text}, "created_at_ms": ts}


A, B = "auth0|alice", "auth0|bob"
check(classify("_smoke-1", [ev(A, 1)], False)[0] == "smoke", "smoke threads are skipped")
check(classify("a/b", [ev(A, 1)], False)[0] == "invalid_id", "ids the planner refuses are skipped")
check(classify("t1", [ev(A, 1)], True)[0] == "owned", "already-owned threads are left alone")
check(classify("t1", [], False)[0] == "no_user_events", "no user events")
check(classify("t1", [ev("guest", 1), ev("", 2)], False)[0] == "guest_only", "guest-only")
check(classify("t1", [ev(A, 1), ev(A, 2)], False) == ("resolvable", A, set()), "creator = first author")
check(classify("t1", [ev(B, 2), ev(A, 1)], False) == ("resolvable", A, {B}),
      "creator by seq, not list order; the later author is reported, not granted")
check(classify("t1", [ev("guest", 1), ev(A, 2)], False) == ("guest_first_then_user", None, {A}),
      "anonymous first event: no creator is guessed")
check(classify("t1", [ev("x/y", 1)], False)[0] == "invalid_id", "a uid with a slash is never written")

e = edge_for("t1", A, [ev(A, 2, "widget_action", ts=200), ev(B, 3), ev(A, 1, text="  Paris   in May ", ts=100)], 900)
check(e["uid"] == A and e["thread_id"] == "t1" and e["role"] == "owner", "edge: creator as owner")
check(e["label"] == "Paris in May", "label: first user_message by seq, whitespace collapsed")
check(e["first_added_at_ms"] == 100 and e["last_activity_ms"] == 900 and e["turn_count"] == 2,
      "first_added / last_activity / creator's turn_count")
check(len(edge_for("t1", A, [ev(A, 1, text="x" * 200)], 0)["label"]) == 80, "label capped at 80")
check(edge_id(A, "t1") == hashlib.sha256((A + "\n" + "t1").encode()).hexdigest(), "edge id matches the planner's")
check(edge_id("a_", "_b") != edge_id("a", "__b") and edge_id("a__b", "c") != edge_id("a", "b__c"),
      "edge ids do not collide where a joined '__' id would")

print("---\nfailures: %d" % len(failures))
sys.exit(1 if failures else 0)
