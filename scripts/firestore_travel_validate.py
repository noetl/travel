#!/usr/bin/env python3
"""READ-ONLY validation of the travel data in Firestore.

Retrieves the travel collections from the live store and checks that they exist,
that documents are retrievable, and that their shape matches what the code that
writes them expects:

  users/{uid}                              profile — playbooks/profile.yaml, written
                                           from adiona/frontend ProfileContext
  users/{uid}/trips/{tripId}/events/{id}   calendar events — itinerary-planner
  chat_threads/{threadId}/events/{id}      planner event log
  chat_threads/{threadId}/slot_state/current
  chat_threads/{threadId}/api_calls/{id}
  catalog/v1/...                           business catalog —
                                           docs/architecture/business-catalog-firestore.md

Usage:

  python3 scripts/firestore_travel_validate.py                 # human report
  python3 scripts/firestore_travel_validate.py --json out.json # + machine report
  python3 scripts/firestore_travel_validate.py --threads all   # walk every thread

Auth: a bearer token from `gcloud auth print-access-token` (any identity with
`roles/datastore.viewer` on the project), or set FIRESTORE_ACCESS_TOKEN.

Exit status: 0 when nothing FAILed (WARNs allowed), 1 on any FAIL, 2 when the store
could not be reached at all.

⚠ READ-ONLY BY CONSTRUCTION, NOT BY CARE. Every request goes through `_call`, which
refuses any method but GET, and any POST that is not one of Firestore's read verbs.
This matters more than it looks: Firestore REST spells its read verbs as
`resource:verb`, and in zsh `"$p:listCollectionIds"` expands `:l` as a LOWERCASE
modifier — the request silently becomes `POST .../documents/catalogistCollectionIds`,
which is a **createDocument**. That exact slip wrote a stray empty document to prod
while this script was being written. A POST to a bare collection path is a write; the
allowlist makes that unrepresentable here. `firestore_travel_validate_test.py` pins it.

This script is deliberately NOT named `*_test.py`: CI runs those without credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_PROJECT = "shastaratech-noetl-prod"
DEFAULT_DATABASE = "(default)"
API = "https://firestore.googleapis.com/v1"

# The only POST verbs Firestore REST uses for reads. Anything else — including a POST to
# a collection path, which is createDocument — is refused.
READ_POST_VERBS = (":listCollectionIds", ":runQuery", ":runAggregationQuery", ":batchGet")

EXPECTED_ROOTS = {"users", "chat_threads", "catalog"}

# --------------------------------------------------------------------- profile schema
# Mirrors adiona/frontend src/types/profile.ts (ProfileState) plus the snake_case
# duplicates ProfileContext.toPlaybookProfile() adds on every save.
PROFILE_CAMEL = {
    "userId": str, "displayName": str, "bio": str, "homeCity": str,
    "preferences": dict, "notifications": dict,
    "bookings": list, "savedTrips": list, "activity": list,
}
PROFILE_SNAKE_MIRROR = {
    "user_id": "userId", "display_name": "displayName", "home_city": "homeCity",
    "saved_trips": "savedTrips",
}
# Keys the playbook itself documents (home_lat/home_lng/interests feed suggest_pois).
PROFILE_PLAYBOOK_KEYS = {"home_lat", "home_lng", "interests", "email", "dietary", "uid"}

BOOKING_REQUIRED = {"id": str, "userId": str, "kind": str, "title": str,
                    "startDate": str, "endDate": str, "amount": (int, float),
                    "currency": str, "status": str}
BOOKING_KINDS = {"flight", "hotel", "car", "activity"}
BOOKING_STATUSES = {"confirmed", "pending", "completed", "cancelled"}
SAVED_TRIP_REQUIRED = {"id": str, "userId": str, "title": str, "destination": str, "savedAt": str}
ACTIVITY_REQUIRED = {"id": str, "text": str, "at": str, "kind": str}
ACTIVITY_KINDS = {"booking", "search", "save", "account"}
MAX_ACTIVITY = 50  # ProfileContext.MAX_ACTIVITY

# Auth0 `sub` shapes the SPA keys profiles on. Anything else under users/ is a
# test/probe id or a defect (e.g. a planner run whose user_uid resolved oddly).
REAL_UID_RE = re.compile(r"^(auth0|google-oauth2|apple|facebook|github|windowslive|email|sms)\|.+")

# ------------------------------------------------------------ calendar event schema
# docs/architecture/data-model.md "Calendar Events".
CAL_REQUIRED = {"type": str, "start_at": str, "timezone": str, "title": str,
                "created_at": str, "updated_at": str}
CAL_TYPES = {"flight_depart", "flight_arrive", "check_in", "check_out", "activity", "user_note"}

# --------------------------------------------------------------- thread event schema
THREAD_EVENT_REQUIRED = {"type": str, "seq": int, "payload": dict, "server_time": str,
                         "thread_path": str}
THREAD_SUBCOLLECTIONS = {"events", "slot_state", "api_calls", "trip", "trips"}


class ReadOnlyViolation(RuntimeError):
    pass


# ======================================================================= transport
def assert_read_only(method: str, url: str) -> None:
    """Raise unless (method, url) is a Firestore READ. Pure; pinned by the test."""
    method = method.upper()
    if method == "GET":
        return
    if method == "POST":
        path = urllib.parse.urlsplit(url).path
        if path.endswith(READ_POST_VERBS):
            return
        raise ReadOnlyViolation(f"refusing POST to {path!r}: not a Firestore read verb "
                                "(a POST to a collection path is createDocument)")
    raise ReadOnlyViolation(f"refusing {method}: this validator is read-only")


class Store:
    def __init__(self, project: str, database: str, token: str):
        self.project = project
        self.database = database
        self.token = token
        self.db_name = f"projects/{project}/databases/{database}"
        self.docs_root = f"{API}/{self.db_name}/documents"
        self.requests = 0

    def _call(self, method: str, url: str, body: dict | None = None) -> dict:
        assert_read_only(method, url)
        self.requests += 1
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
            # User (non-service-account) credentials need a quota project for the
            # Firebase Rules API; harmless for Firestore.
            "x-goog-user-project": self.project})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code} {method} {url}: {e.read()[:300]!r}") from None

    def database_info(self) -> dict:
        return self._call("GET", f"{API}/{self.db_name}")

    def backup_schedules(self) -> list[dict]:
        return self._call("GET", f"{API}/{self.db_name}/backupSchedules").get("backupSchedules", [])

    def firestore_rules_source(self) -> str | None:
        """Source of the released client rules, or None when nothing is released
        (client SDK access is then denied by default)."""
        base = f"https://firebaserules.googleapis.com/v1/projects/{self.project}"
        releases = self._call("GET", f"{base}/releases").get("releases", [])
        rel_ = next((r for r in releases if r.get("name", "").endswith("/releases/cloud.firestore")), None)
        if not rel_:
            return None
        ruleset = self._call("GET", f"https://firebaserules.googleapis.com/v1/{rel_['rulesetName']}")
        return "\n".join(f.get("content", "") for f in (ruleset.get("source") or {}).get("files", []))

    def collection_ids(self, doc_path: str = "") -> list[str]:
        base = f"{self.docs_root}/{doc_path}" if doc_path else self.docs_root
        out, token = [], None
        while True:
            body = {"pageSize": 300}
            if token:
                body["pageToken"] = token
            resp = self._call("POST", base + ":listCollectionIds", body)
            out += resp.get("collectionIds", [])
            token = resp.get("nextPageToken")
            if not token:
                return out

    def list_docs(self, collection_path: str, show_missing: bool = True) -> list[dict]:
        """Every document in a collection, including 'missing' parents (no fields,
        exist only because they have subcollections)."""
        out, token = [], None
        while True:
            q = {"pageSize": 300, "showMissing": str(show_missing).lower()}
            if token:
                q["pageToken"] = token
            resp = self._call("GET", f"{self.docs_root}/{collection_path}?{urllib.parse.urlencode(q)}")
            out += resp.get("documents", [])
            token = resp.get("nextPageToken")
            if not token:
                return out

    def count(self, collection_path: str) -> int:
        """Server-side COUNT of real documents directly under a collection."""
        parent, _, coll = collection_path.rpartition("/")
        base = f"{self.docs_root}/{parent}" if parent else self.docs_root
        body = {"structuredAggregationQuery": {
            "structuredQuery": {"from": [{"collectionId": coll}]},
            "aggregations": [{"alias": "n", "count": {}}]}}
        resp = self._call("POST", base + ":runAggregationQuery", body)
        for row in resp:
            agg = (row.get("result") or {}).get("aggregateFields") or {}
            if "n" in agg:
                return int(agg["n"].get("integerValue", 0))
        return 0


def rel(name: str) -> str:
    return name.split("/documents/", 1)[1] if "/documents/" in name else name


def is_missing(doc: dict) -> bool:
    return "createTime" not in doc


def decode(v: dict):
    if "mapValue" in v:
        return {k: decode(x) for k, x in (v["mapValue"].get("fields") or {}).items()}
    if "arrayValue" in v:
        return [decode(x) for x in v["arrayValue"].get("values") or []]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "nullValue" in v:
        return None
    for k in ("stringValue", "doubleValue", "booleanValue", "timestampValue",
              "referenceValue", "bytesValue", "geoPointValue"):
        if k in v:
            return v[k]
    return v


def fields(doc: dict) -> dict:
    return {k: decode(v) for k, v in (doc.get("fields") or {}).items()}


# ========================================================================= checks
def _is(value, typ) -> bool:
    # `bool` is an int subclass, so True would otherwise pass as an amount or a seq.
    types = typ if isinstance(typ, tuple) else (typ,)
    if isinstance(value, bool) and bool not in types:
        return False
    return isinstance(value, types)


def _type_errors(obj: dict, required: dict, where: str) -> list[str]:
    errs = []
    for key, typ in required.items():
        if key not in obj:
            errs.append(f"{where}: missing {key}")
        elif obj[key] is not None and not _is(obj[key], typ):
            errs.append(f"{where}: {key} is {type(obj[key]).__name__}")
    return errs


def validate_profile(uid: str, data: dict) -> tuple[list[str], list[str]]:
    """(errors, warnings) for one users/{uid} document's fields. Pure."""
    errors, warns = [], []
    if not data:
        warns.append("EMPTY profile document — no fields. This is the signature of "
                     "set_doc(merge=true, data={}) replacing the whole doc (no updateMask), "
                     "i.e. a login-time read on a profile playbook without read_only routing")
        return errors, warns

    for key, typ in PROFILE_CAMEL.items():
        if key in data and data[key] is not None and not _is(data[key], typ):
            errors.append(f"{key} is {type(data[key]).__name__}, expected {typ.__name__}")
    missing_core = [k for k in ("displayName", "preferences", "bookings") if k not in data]
    if missing_core:
        warns.append(f"not written by the current SPA (missing {missing_core}); "
                     "legacy or probe-shaped profile")

    uid_field = data.get("userId", data.get("user_id"))
    if uid_field not in (None, "", uid):
        errors.append(f"userId {uid_field!r} != document id {uid!r}")

    for snake, camel in PROFILE_SNAKE_MIRROR.items():
        if snake in data and camel in data and data[snake] != data[camel]:
            warns.append(f"camel/snake drift: {camel} != {snake}")

    known = set(PROFILE_CAMEL) | set(PROFILE_SNAKE_MIRROR) | PROFILE_PLAYBOOK_KEYS
    unknown = sorted(set(data) - known)
    if unknown:
        warns.append(f"unrecognised top-level keys: {unknown}")

    for i, b in enumerate(data.get("bookings") or []):
        if not isinstance(b, dict):
            errors.append(f"bookings[{i}] is not an object")
            continue
        errors += _type_errors(b, BOOKING_REQUIRED, f"bookings[{i}]")
        if b.get("kind") not in BOOKING_KINDS:
            errors.append(f"bookings[{i}].kind {b.get('kind')!r} not in {sorted(BOOKING_KINDS)}")
        if b.get("status") not in BOOKING_STATUSES:
            errors.append(f"bookings[{i}].status {b.get('status')!r} not in {sorted(BOOKING_STATUSES)}")
        if b.get("userId") not in (None, uid):
            warns.append(f"bookings[{i}].userId {b.get('userId')!r} != owner {uid!r} "
                         "(booking made as a guest before login?)")
        if isinstance(b.get("startDate"), str) and isinstance(b.get("endDate"), str) \
                and b["endDate"][:10] < b["startDate"][:10]:
            errors.append(f"bookings[{i}] ends before it starts")
    ids = [b.get("id") for b in data.get("bookings") or [] if isinstance(b, dict)]
    if len(ids) != len(set(ids)):
        errors.append("duplicate booking ids")

    for i, t in enumerate(data.get("savedTrips") or []):
        if isinstance(t, dict):
            errors += _type_errors(t, SAVED_TRIP_REQUIRED, f"savedTrips[{i}]")
        else:
            errors.append(f"savedTrips[{i}] is not an object")

    act = data.get("activity") or []
    if len(act) > MAX_ACTIVITY:
        warns.append(f"activity has {len(act)} entries > SPA cap {MAX_ACTIVITY}")
    for i, a in enumerate(act):
        if isinstance(a, dict):
            errors += _type_errors(a, ACTIVITY_REQUIRED, f"activity[{i}]")
            if a.get("kind") not in ACTIVITY_KINDS:
                errors.append(f"activity[{i}].kind {a.get('kind')!r}")

    lat, lng = data.get("home_lat"), data.get("home_lng")
    if (lat is None) != (lng is None):
        errors.append("only one of home_lat/home_lng set")
    if data.get("homeCity") and lat is None:
        warns.append("homeCity set but no home_lat/home_lng — profile.yaml suggest_pois "
                     "will never run for this user")
    return errors, warns


def rules_allow_public_user_read(source: str) -> bool:
    """True when a `match /users/...` block grants `allow read: if true`. Pure and
    deliberately coarse: the repo's own firestore.rules (demo project) must trip it."""
    start = source.find("match /users/")
    if start < 0:
        return False
    end = source.find("match ", start + 1)
    block = source[start:end if end > 0 else None]
    return bool(re.search(r"allow\s+(read|get|list)[^;]*:\s*if\s+true\s*;", block))


def validate_calendar_event(data: dict) -> list[str]:
    errs = _type_errors(data, CAL_REQUIRED, "event")
    if data.get("type") not in CAL_TYPES:
        errs.append(f"type {data.get('type')!r} not in {sorted(CAL_TYPES)}")
    return errs


def validate_thread_event(thread_path: str, data: dict) -> list[str]:
    errs = _type_errors(data, THREAD_EVENT_REQUIRED, "event")
    if data.get("thread_path") not in (None, thread_path):
        errs.append(f"thread_path {data.get('thread_path')!r} != {thread_path!r}")
    return errs


# ========================================================================= report
class Report:
    def __init__(self):
        self.rows: list[dict] = []

    def add(self, status: str, check: str, detail: str = "", **extra):
        self.rows.append({"status": status, "check": check, "detail": detail, **extra})
        print(f"[{status:4}] {check}" + (f" — {detail}" if detail else ""))

    def ok(self, c, d="", **x): self.add("PASS", c, d, **x)
    def warn(self, c, d="", **x): self.add("WARN", c, d, **x)
    def fail(self, c, d="", **x): self.add("FAIL", c, d, **x)

    def summary(self) -> dict:
        s = {k: sum(r["status"] == k for r in self.rows) for k in ("PASS", "WARN", "FAIL")}
        return s


def run(store: Store, rep: Report, threads_limit: int | None) -> dict:
    stats: dict = {}

    # ---- database
    info = store.database_info()
    rep.ok("database exists", f"{info['name']} type={info.get('type')} location={info.get('locationId')}")
    if info.get("pointInTimeRecoveryEnablement") != "POINT_IN_TIME_RECOVERY_ENABLED":
        rep.warn("point-in-time recovery disabled",
                 f"versionRetentionPeriod={info.get('versionRetentionPeriod')}: an overwritten or "
                 "deleted profile is unrecoverable after that window")
    if info.get("deleteProtectionState") != "DELETE_PROTECTION_ENABLED":
        rep.warn("database delete protection disabled")
    try:
        schedules = store.backup_schedules()
        (rep.ok if schedules else rep.warn)("backup schedule", f"{len(schedules)} configured")
    except RuntimeError as e:
        rep.warn("backup schedule unreadable", str(e)[:200])

    # ---- client rules: profiles hold bookings, so they must not be world-readable
    try:
        src = store.firestore_rules_source()
        if src is None:
            rep.ok("client rules", "none released — client SDK access denied by default")
        elif rules_allow_public_user_read(src):
            rep.fail("client rules make users/{uid} world-readable",
                     "a released ruleset has `allow read: if true` under /users/")
        else:
            rep.ok("client rules", "released; users/ not world-readable")
    except RuntimeError as e:
        rep.warn("client rules unreadable", str(e)[:200])

    # ---- roots
    roots = store.collection_ids()
    stats["root_collections"] = roots
    for need in ("users", "chat_threads"):
        (rep.ok if need in roots else rep.fail)(f"root collection '{need}' exists")
    stray = sorted(set(roots) - EXPECTED_ROOTS)
    if stray:
        rep.warn("unexpected root collections", ", ".join(stray), stray=stray)

    # ---- users / profiles
    user_docs = store.list_docs("users")
    real_count = store.count("users")
    listed_real = [d for d in user_docs if not is_missing(d)]
    stats["users"] = {"listed": len(user_docs), "real": len(listed_real), "count_agg": real_count,
                      "missing_parents": len(user_docs) - len(listed_real)}
    (rep.ok if real_count == len(listed_real) else rep.fail)(
        "users: aggregation COUNT matches listing", f"count={real_count} listed_real={len(listed_real)}")
    profiles = []
    for d in user_docs:
        uid = rel(d["name"]).split("/", 1)[1]
        kind = "real" if REAL_UID_RE.match(uid) else "test/probe"
        entry = {"uid": uid, "kind": kind, "missing_parent": is_missing(d),
                 "updateTime": d.get("updateTime")}
        if is_missing(d):
            subs = store.collection_ids(f"users/{uid}")
            entry["subcollections"] = subs
            rep.warn(f"users/{uid}: no profile document, only subcollections {subs}",
                     "written by a non-profile path (planner calendar) under a "
                     + ("real" if kind == "real" else "non-Auth0") + " uid")
        else:
            data = fields(d)
            entry["fields"] = sorted(data)
            errs, warns = validate_profile(uid, data)
            entry["errors"], entry["warnings"] = errs, warns
            label = f"users/{uid} [{kind}] profile schema"
            if errs:
                rep.fail(label, "; ".join(errs))
            elif warns:
                rep.warn(label, "; ".join(warns))
            else:
                rep.ok(label, f"{len(data)} fields, {len(data.get('bookings') or [])} bookings")
            entry["subcollections"] = store.collection_ids(f"users/{uid}")
        profiles.append(entry)
    stats["profiles"] = profiles
    if not any(p["kind"] == "real" and not p["missing_parent"] for p in profiles):
        rep.warn("no real (Auth0) profile documents found")

    # ---- calendar events under users/*/trips/*/events
    cal_ok = cal_bad = 0
    for p in profiles:
        if "trips" not in (p.get("subcollections") or []):
            continue
        for trip in store.list_docs(f"users/{p['uid']}/trips"):
            tpath = rel(trip["name"])
            for sub in store.collection_ids(tpath):
                if sub != "events":
                    rep.warn(f"{tpath}: unexpected subcollection {sub!r}")
                    continue
                for ev in store.list_docs(f"{tpath}/events", show_missing=False):
                    errs = validate_calendar_event(fields(ev))
                    if errs:
                        cal_bad += 1
                        rep.fail(f"{rel(ev['name'])}", "; ".join(errs))
                    else:
                        cal_ok += 1
    stats["calendar_events"] = {"valid": cal_ok, "invalid": cal_bad}
    (rep.ok if cal_bad == 0 else rep.fail)("calendar events schema", f"{cal_ok} valid, {cal_bad} invalid")

    # ---- chat threads
    threads = store.list_docs("chat_threads")
    stats["chat_threads"] = {"listed": len(threads),
                             "real_parent_docs": sum(not is_missing(t) for t in threads)}
    rep.ok("chat_threads retrievable", f"{len(threads)} threads "
           f"({stats['chat_threads']['real_parent_docs']} with a parent document)")
    sample = threads if threads_limit is None else threads[:threads_limit]
    ev_total = ev_bad = no_events = seq_dupes = 0
    sub_seen: dict[str, int] = {}
    for t in sample:
        tpath = rel(t["name"])
        subs = store.collection_ids(tpath)
        for s in subs:
            sub_seen[s] = sub_seen.get(s, 0) + 1
        if "events" not in subs:
            no_events += 1
            continue
        evs = store.list_docs(f"{tpath}/events", show_missing=False)
        seqs = []
        for ev in evs:
            data = fields(ev)
            ev_total += 1
            seqs.append(data.get("seq"))
            errs = validate_thread_event(tpath, data)
            if errs:
                ev_bad += 1
                if ev_bad <= 10:
                    rep.fail(rel(ev["name"]), "; ".join(errs))
        if len(seqs) != len(set(seqs)):
            seq_dupes += 1
            rep.warn(f"{tpath}: duplicate event seq values")
    stats["chat_threads"].update({"sampled": len(sample), "events": ev_total, "invalid_events": ev_bad,
                                  "threads_without_events": no_events, "threads_with_seq_dupes": seq_dupes,
                                  "subcollections_seen": sub_seen})
    unexpected_subs = sorted(set(sub_seen) - THREAD_SUBCOLLECTIONS)
    if unexpected_subs:
        rep.warn("chat_threads: unexpected subcollections", ", ".join(unexpected_subs))
    (rep.ok if ev_bad == 0 else rep.fail)(
        "chat_threads events schema", f"{ev_total} events across {len(sample)} sampled threads, {ev_bad} invalid")

    # ---- business catalog
    if "catalog" not in roots:
        rep.warn("business catalog absent", "no catalog/v1 data in this database "
                 "(docs/architecture/business-catalog-firestore.md; noetl/travel#135/#140)")
    else:
        subs = store.collection_ids("catalog/v1")
        stats["catalog_v1"] = {s: store.count(f"catalog/v1/{s}") for s in subs}
        rep.ok("business catalog present", json.dumps(stats["catalog_v1"]))
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--project", default=os.environ.get("GCP_PROJECT", DEFAULT_PROJECT))
    ap.add_argument("--database", default=DEFAULT_DATABASE)
    ap.add_argument("--threads", default="50", help="threads to walk: a number or 'all'")
    ap.add_argument("--json", help="write the machine-readable report here")
    a = ap.parse_args(argv)

    token = os.environ.get("FIRESTORE_ACCESS_TOKEN")
    if not token:
        try:
            token = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True,
                                            stderr=subprocess.PIPE).strip()
        except (OSError, subprocess.CalledProcessError) as e:
            print(f"cannot obtain a token: {e}. Run `gcloud auth login` or set FIRESTORE_ACCESS_TOKEN "
                  f"(needs roles/datastore.viewer on {a.project}).", file=sys.stderr)
            return 2

    store = Store(a.project, a.database, token)
    rep = Report()
    print(f"Firestore travel validation — {store.db_name} (read-only)\n")
    try:
        stats = run(store, rep, None if a.threads == "all" else int(a.threads))
    except RuntimeError as e:
        rep.fail("store reachable", str(e))
        stats = {}
        if not rep.summary()["PASS"]:
            print(f"\n{e}", file=sys.stderr)
            return 2
    s = rep.summary()
    print(f"\n{s['PASS']} pass, {s['WARN']} warn, {s['FAIL']} fail — {store.requests} read requests")
    if a.json:
        with open(a.json, "w") as f:
            json.dump({"database": store.db_name, "summary": s, "checks": rep.rows, "stats": stats},
                      f, indent=2, default=str)
    return 1 if s["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
