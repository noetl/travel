#!/usr/bin/env python3
"""One-time backfill: bring existing chat threads into the per-user thread index.

For every chat_threads/{thread_id}, read the events the CLIENT sent
(`actor.kind == "user"`), attribute the thread to the single uid found on them,
and write, in one Firestore commit per thread:

    thread_owners/{thread_id}          {uid, thread_id, created_at_ms, claimed_by: "backfill"}
                                       -- precondition: must not already exist
    users/{uid}/threads/{thread_id}    {thread_id, thread_path, title, created_at_ms,
                                        last_activity_ms, turn_count, archived: false}

chat_threads/** is only read, never written.

Attribution (see `classify`):
  smoke         `_smoke-` test threads                         skipped
  invalid_id    id the planner would refuse                    skipped
  owned         thread_owners/{id} already exists              skipped (idempotent)
  resolvable    exactly one non-guest uid on the user events   written
  unresolvable  no user events, or only ""/"guest" uids        skipped; the planner
                                                               refuses these threads
  conflict      more than one distinct non-guest uid           skipped; needs a decision

DEFAULT IS A DRY RUN: reads only, prints counts only (no uids, no message text).
Pass --apply to write. Credentials: `gcloud auth print-access-token`, quota
project = --project.

    python3 scripts/backfill_thread_index.py --project shastaratech-noetl-prod
    python3 scripts/backfill_thread_index.py --project shastaratech-noetl-prod --apply
"""
import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
ANONYMOUS = ("", "guest")
TITLE_MAX = 80


def classify(thread_id, user_events, owner_exists):
    """Decide one thread. `user_events` are decoded events with actor.kind == "user".

    Returns (category, uid or None).
    """
    if thread_id.startswith("_smoke-"):
        return "smoke", None
    if not THREAD_ID_RE.match(thread_id):
        return "invalid_id", None
    if owner_exists:
        return "owned", None
    uids = set()
    for ev in user_events:
        uid = str(((ev.get("actor") or {}).get("uid")) or "").strip()
        if uid not in ANONYMOUS:
            uids.add(uid)
    if not uids:
        return "unresolvable", None
    if len(uids) > 1:
        return "conflict", None
    uid = uids.pop()
    if "/" in uid:
        return "invalid_id", None
    return "resolvable", uid


def pointer_for(thread_id, user_events, last_activity_ms):
    """The users/{uid}/threads/{id} document for a resolvable thread."""
    ordered = sorted(user_events, key=lambda e: int(e.get("seq") or 0))
    created = min((int(e.get("created_at_ms") or 0) for e in ordered if e.get("created_at_ms")), default=0)
    title = "New trip"
    for ev in ordered:
        if ev.get("type") == "user_message":
            text = " ".join(str(((ev.get("payload") or {}).get("text")) or "").split())
            if text:
                title = text if len(text) <= TITLE_MAX else text[: TITLE_MAX - 1] + "…"
                break
    return {
        "thread_id": thread_id,
        "thread_path": "chat_threads/" + thread_id,
        "title": title,
        "created_at_ms": created,
        "last_activity_ms": max(last_activity_ms or 0, created),
        "turn_count": len(ordered),
        "archived": False,
    }


# ── Firestore REST ───────────────────────────────────────────────────────────

def _decode(v):
    if "nullValue" in v:
        return None
    if "booleanValue" in v:
        return v["booleanValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "stringValue" in v:
        return v["stringValue"]
    if "mapValue" in v:
        return {k: _decode(x) for k, x in v["mapValue"].get("fields", {}).items()}
    if "arrayValue" in v:
        return [_decode(x) for x in v["arrayValue"].get("values", [])]
    return None


def _encode(v):
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    return {"stringValue": str(v)}


class Store:
    def __init__(self, project, database):
        self.project = project
        self.db_name = "projects/%s/databases/%s" % (project, database)
        self.docs = "https://firestore.googleapis.com/v1/projects/%s/databases/%s/documents" % (
            project, urllib.parse.quote(database, safe="()"))
        self.token = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
        self.calls = 0

    def _call(self, method, url, body=None):
        self.calls += 1
        req = urllib.request.Request(
            url, method=method, data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + self.token, "x-goog-user-project": self.project,
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode() or "{}")

    def thread_ids(self):
        """Every chat_threads/{id}, including ids with no document of their own."""
        ids, token = [], ""
        while True:
            q = {"pageSize": "300", "showMissing": "true", "mask.fieldPaths": "thread_id"}
            if token:
                q["pageToken"] = token
            page = self._call("GET", self.docs + "/chat_threads?" + urllib.parse.urlencode(q))
            for d in page.get("documents", []):
                ids.append(d["name"].rsplit("/", 1)[1])
            token = page.get("nextPageToken")
            if not token:
                return ids

    def _query(self, parent, structured):
        rows = self._call("POST", self.docs + "/" + parent + ":runQuery", {"structuredQuery": structured})
        return [{k: _decode(v) for k, v in r["document"].get("fields", {}).items()}
                for r in rows if "document" in r]

    def user_events(self, thread_id, with_text):
        """Events the client sent. Older events may lack `actor.kind`, so fall
        back to `type == "user_message"` when the actor filter finds none."""
        fields = ["actor", "created_at_ms", "seq", "type"] + (["payload.text"] if with_text else [])

        def by(field, value):
            return self._query("chat_threads/" + thread_id, {
                "from": [{"collectionId": "events"}],
                "where": {"fieldFilter": {"field": {"fieldPath": field}, "op": "EQUAL",
                                          "value": {"stringValue": value}}},
                "select": {"fields": [{"fieldPath": f} for f in fields]},
                "limit": 5000,
            })

        return by("actor.kind", "user") or by("type", "user_message")

    def last_activity_ms(self, thread_id):
        rows = self._query("chat_threads/" + thread_id, {
            "from": [{"collectionId": "events"}],
            "orderBy": [{"field": {"fieldPath": "seq"}, "direction": "DESCENDING"}],
            "select": {"fields": [{"fieldPath": "created_at_ms"}]},
            "limit": 1,
        })
        return int(rows[0].get("created_at_ms") or 0) if rows else 0

    def exists(self, rel):
        try:
            self._call("GET", self.docs + "/" + rel + "?mask.fieldPaths=uid")
            return True
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return False
            raise

    def commit_claim(self, thread_id, uid, pointer):
        owner = {"uid": uid, "thread_id": thread_id, "created_at_ms": pointer["created_at_ms"],
                 "claimed_by": "backfill"}
        writes = [
            {"update": {"name": "%s/documents/thread_owners/%s" % (self.db_name, thread_id),
                        "fields": {k: _encode(v) for k, v in owner.items()}},
             "currentDocument": {"exists": False}},
            {"update": {"name": "%s/documents/users/%s/threads/%s" % (self.db_name, uid, thread_id),
                        "fields": {k: _encode(v) for k, v in pointer.items()}},
             "updateMask": {"fieldPaths": sorted(pointer)}},
        ]
        self._call("POST", self.docs.rsplit("/documents", 1)[0] + "/documents:commit", {"writes": writes})


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", required=True)
    ap.add_argument("--database", default="(default)")
    ap.add_argument("--apply", action="store_true", help="write the index (default: dry run)")
    args = ap.parse_args()

    store = Store(args.project, args.database)
    started = time.time()
    ids = store.thread_ids()
    counts = {k: 0 for k in ("smoke", "invalid_id", "owned", "resolvable", "unresolvable", "conflict")}
    uids, user_events_total, written, write_errors = set(), 0, 0, 0
    unresolvable_no_events = 0

    for tid in ids:
        owner_exists = THREAD_ID_RE.match(tid) and not tid.startswith("_smoke-") and store.exists("thread_owners/" + tid)
        events = [] if (tid.startswith("_smoke-") or not THREAD_ID_RE.match(tid) or owner_exists) \
            else store.user_events(tid, with_text=args.apply)
        user_events_total += len(events)
        category, uid = classify(tid, events, bool(owner_exists))
        counts[category] += 1
        if category == "unresolvable" and not events:
            unresolvable_no_events += 1
        if category != "resolvable":
            continue
        uids.add(uid)
        if args.apply:
            try:
                store.commit_claim(tid, uid, pointer_for(tid, events, store.last_activity_ms(tid)))
                written += 1
            except urllib.error.HTTPError as exc:
                write_errors += 1
                print("write failed for one thread: HTTP %s" % exc.code, file=sys.stderr)

    report = {
        "mode": "APPLY" if args.apply else "DRY-RUN (read-only)",
        "project": args.project,
        "threads_found": len(ids),
        "by_category": counts,
        "distinct_uids_resolvable": len(uids),
        "unresolvable_with_no_user_events": unresolvable_no_events,
        "unresolvable_guest_only": counts["unresolvable"] - unresolvable_no_events,
        "user_events_scanned": user_events_total,
        "would_write" if not args.apply else "written": counts["resolvable"] if not args.apply else written,
        "write_errors": write_errors,
        "api_calls": store.calls,
        "seconds": round(time.time() - started, 1),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
