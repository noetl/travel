#!/usr/bin/env python3
"""Attribution rules of scripts/backfill_thread_index.py (pure functions, no network)."""
import sys

sys.path.insert(0, "scripts")
from backfill_thread_index import classify, pointer_for  # noqa: E402

failures = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


def ev(uid, seq, type_="user_message", text="", ts=0):
    return {"actor": {"kind": "user", "uid": uid}, "seq": seq, "type": type_,
            "payload": {"text": text}, "created_at_ms": ts}


A, B = "auth0|alice", "auth0|bob"
check(classify("_smoke-1", [ev(A, 1)], False) == ("smoke", None), "smoke threads are skipped")
check(classify("a/b", [ev(A, 1)], False)[0] == "invalid_id", "ids the planner refuses are skipped")
check(classify("t1", [ev(A, 1)], True) == ("owned", None), "already-owned threads are left alone")
check(classify("t1", [ev(A, 1), ev(A, 2)], False) == ("resolvable", A), "one uid: resolvable")
check(classify("t1", [ev("guest", 1), ev(A, 2)], False) == ("resolvable", A), "guest turns do not block attribution")
check(classify("t1", [ev("guest", 1), ev("", 2)], False) == ("unresolvable", None), "guest-only: unresolvable")
check(classify("t1", [], False) == ("unresolvable", None), "no user events: unresolvable")
check(classify("t1", [ev(A, 1), ev(B, 2)], False) == ("conflict", None), "two uids: conflict, not guessed")
check(classify("t1", [ev("x/y", 1)], False)[0] == "invalid_id", "a uid with a slash is never written as a path")

p = pointer_for("t1", [ev(A, 2, "widget_action", ts=200), ev(A, 1, text="  Paris   in May ", ts=100)], 900)
check(p["title"] == "Paris in May", "title: first user_message by seq, whitespace collapsed")
check(p["created_at_ms"] == 100 and p["last_activity_ms"] == 900 and p["turn_count"] == 2,
      "created/last-activity/turn_count")
check(p["archived"] is False and p["thread_path"] == "chat_threads/t1", "pointer shape")
check(len(pointer_for("t1", [ev(A, 1, text="x" * 200)], 0)["title"]) == 80, "title capped at 80")
check(pointer_for("t1", [ev(A, 1, "widget_action")], 0)["title"] == "New trip", "no message text: default title")

print("---\nfailures: %d" % len(failures))
sys.exit(1 if failures else 0)
