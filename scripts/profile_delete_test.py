#!/usr/bin/env python3
"""Guard: profile.yaml's delete branch is interlocked and reports only what the store shows.

Runs the playbook's OWN validate_input and build_delete_response code (no external calls).
"""
import sys

import yaml

doc = yaml.safe_load(open("playbooks/profile.yaml"))
steps = {s["step"]: s for s in doc["workflow"]}
failures = []
checks = 0


def check(label, got, expect):
    global checks
    checks += 1
    ok = got == expect
    print("  %-64s expect=%-10r got=%-10r %s" % (label, expect, got, "OK" if ok else "FAIL"))
    if not ok:
        failures.append(label)


def validate(**kw):
    ns = {"uid": "qa-1", "profile": {}, "read_only": False, "delete": False}
    ns.update(kw)
    exec(steps["validate_input"]["tool"]["code"], ns)
    return ns["result"]


print("the delete flag:")
for value, expect in [(True, True), ("true", True), (" YES ", True), ("on", True), (1, True),
                      (False, False), ("false", False), ("0", False), ("", False), (None, False),
                      ("delete", False), ("nope", False), ([], False)]:
    check("delete=%r -> %s" % (value, expect), validate(delete=value).get("delete"), expect)

print("\ninterlocks:")
r = validate(delete=True, profile={"displayName": "A"})
check("delete with a non-empty profile is REFUSED", r["ok"], False)
r = validate(delete=True, read_only=True)
check("delete together with read_only is REFUSED", r["ok"], False)
r = validate(delete=True, uid=" ")
check("delete with a blank uid is REFUSED", r["ok"], False)
r = validate(delete=True)
check("delete with uid and an empty profile is accepted", (r["ok"], r["doc_path"]), (True, "users/qa-1"))
check("a normal save is not a delete", validate(profile={"a": 1}).get("delete"), False)

print("\nrouting:")
arcs = steps["validate_input"]["next"]["arcs"]
names = [a["step"] for a in arcs]
check("delete arc precedes the save arc", names.index("delete_profile") < names.index("save_profile"), True)
check("delete arc requires ok and delete", "validate_input.delete" in arcs[names.index("delete_profile")]["when"], True)
check("delete_profile uses delete_doc", steps["delete_profile"]["tool"]["payload"]["tool"], "delete_doc")
check("delete_profile -> confirm_deleted",
      [a["step"] for a in steps["delete_profile"]["next"]["arcs"]], ["confirm_deleted"])
check("confirm_deleted re-reads with get_doc", steps["confirm_deleted"]["tool"]["payload"]["tool"], "get_doc")
check("the delete branch never reaches save_profile or set_doc",
      any(s in ("save_profile", "load_profile") for s in
          [a["step"] for st in ("delete_profile", "confirm_deleted", "build_delete_response")
           for a in steps[st]["next"]["arcs"]]), False)
check("workload.delete defaults to False", doc["workload"].get("delete"), False)

print("\nthe response:")


def respond(deleted, confirmed):
    ns = {"validated": {"uid": "qa-1"}, "deleted": deleted, "confirmed": confirmed}
    exec(steps["build_delete_response"]["tool"]["code"], ns)
    return ns["result"]


ok_del = {"data": {"ok": True, "path": "users/qa-1", "deleted": True, "not_found": False}}
gone = {"data": {"ok": True, "found": False, "path": "users/qa-1", "document": None}}
still = {"data": {"ok": True, "found": True, "path": "users/qa-1", "document": {"data": {"a": 1}}}}
r = respond(ok_del, gone)
check("delete + document gone -> deleted", (r["ok"], r["deleted"], r["found_after_delete"]), (True, True, False))
check("...and never claims a save", r["saved"], False)
r = respond(ok_del, still)
check("document still present -> NOT deleted", (r["ok"], r["deleted"]), (False, False))
r = respond(ok_del, {"data": {"ok": False, "error": "boom"}})
check("read-back failed -> NOT reported as deleted", r["deleted"], False)
r = respond({"data": {"ok": False, "error": "403"}}, gone)
check("provider error -> NOT deleted, error surfaced", (r["deleted"], r["error"]), (False, "403"))
r = respond({"data": {"ok": True, "deleted": False, "not_found": True}}, gone)
check("already absent -> deleted (idempotent), was_absent", (r["deleted"], r["was_absent"]), (True, True))

print("\n%d check(s) performed, %d failure(s)" % (checks, len(failures)))
if checks < 30:
    print("FAIL: fewer checks ran than this guard claims")
    sys.exit(1)
sys.exit(1 if failures else 0)
