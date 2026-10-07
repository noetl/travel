#!/usr/bin/env python3
"""Regression test: the calendar render step must read fields from `data`.

``playbooks/catalog/calendar/list.yaml``, step ``render_calendar_widget``.

⚠ WHY THIS EXISTS — measured against prod on 2026-10-07.

The step filtered documents with ``if doc.get("event_id")``. But
``query_collection`` returns each document in the connector's plain-doc wrapper::

    {"name": …, "path": …, "createTime": …, "updateTime": …, "data": {…fields…}}

built by its ``_plain_doc``. The decoded Firestore fields live under ``data``, so
``doc["event_id"]`` is ALWAYS absent and **every document was filtered out**.

Against ``chat_threads/chat-mtalhs7m-78hi4c`` the live Firestore project held **12**
event documents and the playbook returned ``event_count: 0`` — after it had already
been fixed for a rejected tool kind, a dead project pin, and a missing ``start``
step. Four defects in one playbook, and this was the one that survived all three
earlier fixes because **an empty calendar is exactly what a wrong-project read looks
like**, so zero never read as suspicious.

The playbook's own comment asserted the opposite of the truth: "Each document is a
plain dict with the Firestore field values already decoded". Confidently wrong
comments are why the fixture below uses the REAL wrapper shape.

Runs the playbook's own embedded code. No network.
"""
import re
import sys

import yaml

PLAYBOOK = "playbooks/catalog/calendar/list.yaml"
steps = {s["step"]: s for s in yaml.safe_load(open(PLAYBOOK))["workflow"]}

failures = []
checks = 0


def check(label, got, expect):
    global checks
    checks += 1
    ok = got == expect
    print("  %-60s expect=%-6s got=%-6s %s" % (label, expect, got, "OK" if ok else "FAIL"))
    if not ok:
        failures.append(label)


def run(step_name, **inputs):
    env = dict(inputs)
    exec(steps[step_name]["tool"]["code"], env)  # noqa: S102
    return env["result"]


THREAD = "chat_threads/chat-mtalhs7m-78hi4c"
COLL = THREAD + "/trip/current/events"


def wrapped(event_id, start_at, title):
    """A document exactly as query_collection returns it — fields under `data`."""
    return {
        "name": "projects/p/databases/(default)/documents/" + COLL + "/" + event_id,
        "path": COLL + "/" + event_id,
        "createTime": "2026-10-01T00:00:00Z",
        "updateTime": "2026-10-01T00:00:00Z",
        "data": {
            "event_id": event_id,
            "type": "flight_depart",
            "start_at": start_at,
            "end_at": None,
            "title": title,
            "timezone": "America/Los_Angeles",
        },
    }


# ------------------------------------------------------- resolve_collection_path
print("resolve_collection_path")
r = run("resolve_collection_path", user_uid=None, trip_id="current", thread_path=THREAD)
check("anonymous thread path", r["collection_path"], COLL)
r2 = run("resolve_collection_path", user_uid="auth0|abc", trip_id="t1", thread_path="")
check("authenticated user path", r2["collection_path"], "users/auth0|abc/trips/t1/events")
for uid in ("guest", "null", ""):
    rr = run("resolve_collection_path", user_uid=uid, trip_id="current", thread_path=THREAD)
    check("user_uid=%-6r treated as anonymous" % uid, rr["collection_path"], COLL)

# ------------------------------------------------------------ the wrapper shape
print("\nrender_calendar_widget — fields live under `data`")
def envelope(data):
    """What a `kind: playbook` child of the Firestore MCP actually hands back:
    the MCP envelope, read by the BARE STEP NAME. `{{ step.result }}` resolves to
    nothing -- that is the defect that returned 0 events against 12 documents."""
    return {"isError": False, "summary": "query_collection %s" % COLL, "data": data}


QUERY_REPLY = envelope({
    "collection_path": COLL,
    "count": 3,
    "documents": [
        wrapped("e3", "2026-11-03T08:00:00Z", "Depart SFO"),
        wrapped("e1", "2026-11-01T08:00:00Z", "Check in"),
        wrapped("e2", "2026-11-02T08:00:00Z", "Activity"),
    ],
})
res = run("render_calendar_widget", trip_id="current", collection_path=COLL,
          query_result=QUERY_REPLY)
check("all three wrapped documents survive", res["event_count"], 3)
check("sorted by start_at", [e["event_id"] for e in res["display_events"]], ["e1", "e2", "e3"])
check("a field from `data` is present", res["display_events"][0].get("title"), "Check in")
check("the envelope is the closed widget contract",
      res["envelope"]["widget_type"], "calendar_view")
check("schema_version pinned", res["envelope"]["schema_version"], 1)
check("events_path echoed", res["envelope"]["payload"]["events_path"], COLL)

# a document with no event_id is still excluded
noisy = envelope({"collection_path": COLL, "count": 2, "documents": [
    wrapped("e1", "2026-11-01T08:00:00Z", "Check in"),
    {"path": COLL + "/junk", "data": {"type": "user_note"}},
]})
res2 = run("render_calendar_widget", trip_id="current", collection_path=COLL,
           query_result=noisy)
check("a document without event_id is excluded", res2["event_count"], 1)

# forward tolerance: an already-flat document must also work
flat = envelope({"collection_path": COLL, "count": 1, "documents": [
    {"event_id": "f1", "start_at": "2026-11-01T08:00:00Z", "title": "Flat"}]})
res3 = run("render_calendar_widget", trip_id="current", collection_path=COLL,
           query_result=flat)
check("an already-flat document also works", res3["event_count"], 1)

# --------------------------------------------------------------- RED CONTROL
# The exact prod bug: fields at the top level is what the OLD code assumed, so a
# fixture in that shape must NOT be what makes the test pass. Feed the wrapper and
# strip `data` — nothing should survive, which is what the bug produced against 12
# real documents. If this control ever returns 3, the test has stopped
# discriminating and every check above is decorative.
print("\nRED CONTROL — the pre-fix assumption must yield nothing")
stripped = envelope({"collection_path": COLL, "count": 3, "documents": [
    {k: v for k, v in wrapped("e%d" % i, "2026-11-0%dT08:00:00Z" % i, "t").items()
     if k != "data"} for i in (1, 2, 3)]})
res4 = run("render_calendar_widget", trip_id="current", collection_path=COLL,
           query_result=stripped)
check("documents with no `data` and no top-level fields yield 0 (control)",
      res4["event_count"], 0)

# an un-unwrapped envelope (data left in place) must still not be mistaken for data
print("\nthe envelope is unwrapped, and the denominator is published")
check("documents_returned echoes the provider count", res["documents_returned"], 3)
check("deref_error is reported as a channel", "deref_error" in res, True)
check("provider_error is reported as a channel", "provider_error" in res, True)

# --------------------------------------------------- RED CONTROL 2: the accessor
# The pre-fix playbook read `{{ query_calendar_events.result }}`, which resolves to
# nothing, so the step received {} and reported 0 with a clean COMPLETED. Feeding {}
# must therefore produce 0 -- and the STRUCTURAL check below is what actually stops
# the accessor regressing, because no fixture can detect a template that resolves to
# nothing.
print("\nRED CONTROL 2 -- a resolved-to-nothing accessor yields 0")
res_empty = run("render_calendar_widget", trip_id="current", collection_path=COLL,
                query_result={})
check("an empty envelope yields 0 (control)", res_empty["event_count"], 0)

print("\nstructural: no step may read a child playbook's output via `.result`")
doc_all = yaml.safe_load(open(PLAYBOOK))
child_steps = [s["step"] for s in doc_all["workflow"] if s["tool"].get("kind") == "playbook"]
check("found child playbook steps to check", len(child_steps) >= 1, True)
body = open(PLAYBOOK).read()
for cs in child_steps:
    # ignore prose: only flag it inside a `{{ ... }}` template expression
    bad = re.findall(r"\{\{[^}]*\b%s\.result\b[^}]*\}\}" % re.escape(cs), body)
    check("`%s` is not read via .result" % cs, bad, [])

print("\n%d checks, %d failed" % (checks, len(failures)))
if failures:
    for f in failures:
        print("  FAILED: %s" % f)
    sys.exit(1)
print("PASS")
