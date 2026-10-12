#!/usr/bin/env python3
"""Offline guard for scripts/firestore_travel_validate.py — no network, no credentials.

Pins the two things that must not regress:

  1. The transport is READ-ONLY. In particular the exact URL a zsh `:l` modifier turned a
     `:listCollectionIds` read into — `POST .../documents/catalogistCollectionIds`, a
     createDocument — must be refused.
  2. The profile schema rules agree with adiona/frontend's ProfileState, including the
     empty-document signature of `set_doc(merge=true, data={})`.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
import firestore_travel_validate as v  # noqa: E402

failures = []
checks = 0


def check(label, cond):
    global checks
    checks += 1
    print("  %-70s %s" % (label, "OK" if cond else "FAIL"))
    if not cond:
        failures.append(label)


def refused(method, url):
    try:
        v.assert_read_only(method, url)
        return False
    except v.ReadOnlyViolation:
        return True


DOCS = "https://firestore.googleapis.com/v1/projects/p/databases/(default)/documents"

print("read-only transport")
check("GET a document is allowed", not refused("GET", f"{DOCS}/users/u1"))
check("POST :listCollectionIds is allowed", not refused("POST", f"{DOCS}/users/u1:listCollectionIds"))
check("POST root :listCollectionIds is allowed", not refused("POST", f"{DOCS}:listCollectionIds"))
check("POST :runAggregationQuery is allowed", not refused("POST", f"{DOCS}:runAggregationQuery"))
check("POST :runQuery is allowed", not refused("POST", f"{DOCS}/users:runQuery"))
check("zsh-mangled 'catalogistCollectionIds' POST (createDocument) is REFUSED",
      refused("POST", f"{DOCS}/catalogistCollectionIds"))
check("POST to a collection path (createDocument) is REFUSED", refused("POST", f"{DOCS}/users"))
check("verb in the query string does not launder a POST",
      refused("POST", f"{DOCS}/users?x=:listCollectionIds"))
check("PATCH (set_doc) is REFUSED", refused("PATCH", f"{DOCS}/users/u1"))
check("DELETE is REFUSED", refused("DELETE", f"{DOCS}/users/u1"))
check("POST :commit is REFUSED", refused("POST", f"{DOCS}:commit"))
check("POST :batchWrite is REFUSED", refused("POST", f"{DOCS}:batchWrite"))

print("profile schema")
UID = "auth0|abc"
good = {
    "userId": UID, "user_id": UID, "displayName": "A", "display_name": "A", "bio": "",
    "homeCity": "Lisbon", "home_city": "Lisbon", "home_lat": 38.7, "home_lng": -9.1,
    "preferences": {}, "notifications": {}, "savedTrips": [], "saved_trips": [], "activity": [],
    "bookings": [{"id": "bk-1", "userId": UID, "kind": "hotel", "title": "H", "startDate": "2026-10-01",
                  "endDate": "2026-10-03", "amount": 250, "currency": "USD", "status": "confirmed"}],
}
errs, warns = v.validate_profile(UID, good)
check("a current-SPA profile has no errors", errs == [])
check("...and no warnings", warns == [])

errs, warns = v.validate_profile(UID, {})
check("an EMPTY doc is flagged as the merge-wipe signature", any("EMPTY" in w for w in warns))

bad = dict(good, bookings=[dict(good["bookings"][0], amount=True, kind="boat", status="ok")])
errs, _ = v.validate_profile(UID, bad)
check("a bool amount is a type error (bool is an int subclass)", any("amount" in e for e in errs))
check("an unknown booking kind is an error", any(".kind" in e for e in errs))
check("an unknown booking status is an error", any(".status" in e for e in errs))

errs, _ = v.validate_profile(UID, dict(good, userId="auth0|other"))
check("userId that disagrees with the doc id is an error", any("userId" in e for e in errs))

_, warns = v.validate_profile(UID, dict(good, display_name="B"))
check("camel/snake drift is warned", any("drift" in w for w in warns))

no_coords = {k: x for k, x in good.items() if k not in ("home_lat", "home_lng")}
_, warns = v.validate_profile(UID, no_coords)
check("homeCity without coordinates warns that suggestions never run",
      any("suggest_pois" in w for w in warns))

print("client rules")
REPO_RULES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "firestore.rules")
check("the repo's demo firestore.rules is detected as world-readable users/",
      v.rules_allow_public_user_read(open(REPO_RULES).read()))
check("an owner-only users/ rule is not flagged", not v.rules_allow_public_user_read(
    "match /users/{uid}/{document=**} {\n allow read: if request.auth.uid == uid;\n}\n"
    "match /chat_threads/{t} { allow read: if true; }"))

print("event schemas")
check("a valid calendar event passes", v.validate_calendar_event({
    "type": "check_in", "start_at": "x", "timezone": "UTC", "title": "t",
    "created_at": "x", "updated_at": "x"}) == [])
check("an unknown calendar event type fails", v.validate_calendar_event({
    "type": "nap", "start_at": "x", "timezone": "UTC", "title": "t",
    "created_at": "x", "updated_at": "x"}) != [])
check("a thread event under the wrong thread_path fails", v.validate_thread_event(
    "chat_threads/a", {"type": "t", "seq": 1, "payload": {}, "server_time": "x",
                       "thread_path": "chat_threads/b"}) != [])

print("\n%d checks, %d failed" % (checks, len(failures)))
sys.exit(1 if failures else 0)
