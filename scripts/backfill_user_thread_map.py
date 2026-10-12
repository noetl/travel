#!/usr/bin/env python3
"""One-time backfill: populate the user<->thread relation from existing threads.

For every chat_threads/{thread_id}, read the events the CLIENT sent
(`actor.kind == "user"`, falling back to `type == "user_message"`) and, for a
thread whose creator can be established, write in one Firestore commit:

    thread_owners/{thread_id}                 {uid, thread_id, created_at_ms, claimed_by: "backfill"}
                                              -- precondition: must not already exist
    user_thread_map/{sha256(uid + "\n" + id)} the creator's edge: role "owner", label,
                                              first_added_at_ms, last_activity_ms, turn_count

chat_threads/** is only read, never written.

THE CREATOR is the author of the thread's EARLIEST user event (lowest seq).
Mirroring the planner's first-access rule, nobody else gets an edge from
history: posting to a thread id never granted membership, so a later author is
counted (`later_authors_not_granted`) but not written.

Categories (see `classify`):
  smoke                    `_smoke-` test threads                       skipped
  invalid_id               id the planner would refuse                  skipped
  owned                    thread_owners/{id} already exists            skipped (idempotent)
  no_user_events           nothing the client sent                      skipped
  guest_only               every user event is ""/"guest"               skipped
  guest_first_then_user    first event anonymous, a signed-in uid later skipped; needs a
                           (could be the same person after login, or    product call
                           someone else -- history cannot tell)
  resolvable               first user event carries a signed-in uid     written

DEFAULT IS A DRY RUN: reads only, prints counts only (no uids, no message text).
Pass --apply to write. Credentials: `gcloud auth print-access-token`, quota
project = --project.

    python3 scripts/backfill_user_thread_map.py --project shastaratech-noetl-prod
    python3 scripts/backfill_user_thread_map.py --project shastaratech-noetl-prod --apply
"""
import argparse
import hashlib
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


def edge_id(uid, thread_id):
    """Same id as the planner and muno/playbooks/threads."""
    return hashlib.sha256((uid + "\n" + thread_id).encode("utf-8")).hexdigest()


def _uid(ev):
    return str(((ev.get("actor") or {}).get("uid")) or "").strip()


def classify(thread_id, user_events, owner_exists):
    """Decide one thread. Returns (category, creator_uid or None, later_author_uids)."""
    if thread_id.startswith("_smoke-"):
        return "smoke", None, set()
    if not THREAD_ID_RE.match(thread_id):
        return "invalid_id", None, set()
    if owner_exists:
        return "owned", None, set()
    if not user_events:
        return "no_user_events", None, set()
    ordered = sorted(user_events, key=lambda e: int(e.get("seq") or 0))
    signed_in = {_uid(e) for e in ordered} - set(ANONYMOUS)
    if not signed_in:
        return "guest_only", None, set()
    creator = _uid(ordered[0])
    if creator in ANONYMOUS:
        return "guest_first_then_user", None, signed_in
    if "/" in creator:
        return "invalid_id", None, set()
    return "resolvable", creator, signed_in - {creator}


def edge_for(thread_id, creator, user_events, last_activity_ms):
    """The creator's user_thread_map edge for a resolvable thread."""
    ordered = sorted(user_events, key=lambda e: int(e.get("seq") or 0))
    created = min((int(e.get("created_at_ms") or 0) for e in ordered if e.get("created_at_ms")), default=0)
    label = "New trip"
    for ev in ordered:
        if ev.get("type") == "user_message":
            text = " ".join(str(((ev.get("payload") or {}).get("text")) or "").split())
            if text:
                label = text if len(text) <= TITLE_MAX else text[: TITLE_MAX - 1] + "\u2026"
                break
    return {
        "uid": creator,
        "thread_id": thread_id,
        "thread_path": "chat_threads/" + thread_id,
        "role": "owner",
        "label": label,
        "first_added_at_ms": created,
        "last_activity_ms": max(last_activity_ms or 0, created),
        "turn_count": sum(1 for e in ordered if _uid(e) == creator),
        "archived": False,
        "added_by": "backfill",
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

    def commit_claim(self, thread_id, edge):
        owner = {"uid": edge["uid"], "thread_id": thread_id, "created_at_ms": edge["first_added_at_ms"],
                 "claimed_by": "backfill"}
        writes = [
            {"update": {"name": "%s/documents/thread_owners/%s" % (self.db_name, thread_id),
                        "fields": {k: _encode(v) for k, v in owner.items()}},
             "currentDocument": {"exists": False}},
            {"update": {"name": "%s/documents/user_thread_map/%s" % (self.db_name, edge_id(edge["uid"], thread_id)),
                        "fields": {k: _encode(v) for k, v in edge.items()}},
             "updateMask": {"fieldPaths": sorted(edge)}},
        ]
        self._call("POST", self.docs.rsplit("/documents", 1)[0] + "/documents:commit", {"writes": writes})


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", required=True)
    ap.add_argument("--database", default="(default)")
    ap.add_argument("--apply", action="store_true", help="write the relation (default: dry run)")
    args = ap.parse_args()

    store = Store(args.project, args.database)
    started = time.time()
    ids = store.thread_ids()

    categories = ("smoke", "invalid_id", "owned", "no_user_events", "guest_only",
                  "guest_first_then_user", "resolvable")
    counts = {k: 0 for k in categories}
    creators, later_authors, user_events_total, written, write_errors = set(), set(), 0, 0, 0
    later_author_edges = 0
    for tid in ids:
        valid = bool(THREAD_ID_RE.match(tid)) and not tid.startswith("_smoke-")
        owner_exists = valid and store.exists("thread_owners/" + tid)
        events = store.user_events(tid, with_text=args.apply) if valid and not owner_exists else []
        user_events_total += len(events)
        category, creator, later = classify(tid, events, owner_exists)
        counts[category] += 1
        later_authors |= later
        if category == "resolvable":
            later_author_edges += len(later)
        if category != "resolvable":
            continue
        creators.add(creator)
        if args.apply:
            try:
                store.commit_claim(tid, edge_for(tid, creator, events, store.last_activity_ms(tid)))
                written += 1
            except urllib.error.HTTPError as exc:
                write_errors += 1
                print("write failed for one thread: HTTP %s" % exc.code, file=sys.stderr)

    report = {
        "mode": "APPLY" if args.apply else "DRY-RUN (read-only)",
        "project": args.project,
        "threads_found": len(ids),
        "by_category": counts,
        "distinct_creator_uids": len(creators),
        "distinct_later_author_uids_not_granted": len(later_authors),
        "later_author_edges_not_written": later_author_edges,
        "user_events_scanned": user_events_total,
        ("written" if args.apply else "would_write_threads"): written if args.apply else counts["resolvable"],
        "would_write_documents": 2 * counts["resolvable"],
        "write_errors": write_errors,
        "api_calls": store.calls,
        "seconds": round(time.time() - started, 1),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
