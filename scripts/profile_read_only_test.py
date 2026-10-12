#!/usr/bin/env python3
"""Regression test: a login-time profile READ must not write to Firestore.

adiona/frontend#59.

The SPA sends ``{"uid": "...", "profile": {}, "read_only": true}`` at login to load a
profile. Before this fix the playbook routed ``validate_input -> save_profile``
unconditionally, so every login performed a Firestore ``set_doc``.

⚠ That WAS data loss. The Firestore provider only adds ``updateMask`` when ``data`` is
non-empty, and a ``PATCH`` without a mask is a full replace — so ``set_doc(merge=true,
data={})`` overwrote the profile with zero fields on every login. It was also:

  * a write on a read path, on the login critical path, behind ``timeout: 60``;
  * and because ``set`` with ``merge`` CREATES the document, after one login
    "this user never saved a profile" became indistinguishable from "saved an empty
    one".

Runs the playbook's OWN embedded code (no external calls), in the style of
``planner_flow_advance_test.py``.
"""
import sys

import yaml

PLAYBOOK = "playbooks/profile.yaml"
doc = yaml.safe_load(open(PLAYBOOK))

failures = []
checks = 0


def check(label, got, expect):
    global checks
    checks += 1
    ok = got == expect
    print("  %-56s expect=%-7s got=%-7s %s" % (label, expect, got, "OK" if ok else "FAIL"))
    if not ok:
        failures.append(label)


# ---------------------------------------------------------------- the flag parse
validate = next(s for s in doc["workflow"] if s.get("step") == "validate_input")
code = validate["tool"]["code"]

# ⚠ The normalisation is EXTRACTED from the playbook rather than restated here. A test
# that reimplements the logic it checks passes whenever the two copies agree, which is
# exactly when it is least useful.
import re  # noqa: E402

m = re.search(r"(if isinstance\(read_only, bool\):.*?_read_only = False)", code, re.S)
if not m:
    print("FAIL: could not extract the read_only normalisation from %s" % PLAYBOOK)
    print("      The guard cannot test a block it did not find — this is a failure, not a pass.")
    sys.exit(1)
block = m.group(1)
print("extracted %d bytes of the playbook's own normalisation" % len(block))

print("\nread_only normalisation:")
for value, expect, note in [
    (True, True, "YAML bool"),
    (False, False, "YAML bool"),
    ("true", True, "string"),
    ("True", True, "capitalised"),
    ("  true ", True, "whitespace"),
    ("1", True, "string 1"),
    ("yes", True, ""),
    ("on", True, ""),
    # ⚠ The trap: bool("false") is True. A plain truthiness test would route a real
    # SAVE down the read path and look like it worked.
    ("false", False, "bool('false') is True — the trap"),
    ("False", False, "capitalised"),
    ("0", False, ""),
    ("", False, "empty"),
    # Anything unrecognised must mean WRITE. Defaulting an unknown value to read-only
    # would silently stop saving profiles altogether, which is far worse than an
    # unnecessary write.
    ("nonsense", False, "unrecognised -> WRITE"),
    (1, True, "int"),
    (0, False, "int"),
    (None, False, "None -> WRITE"),
]:
    ns = {"read_only": value}
    exec(block, {}, ns)  # noqa: S102 - the point of this test
    check("read_only=%r %s" % (value, note), ns["_read_only"], expect)


# ------------------------------------------------------------------- the routing
print("\nrouting:")
arcs = validate["next"]["arcs"]
check("validate_input has 4 arcs (read, delete, save, reject)", len(arcs), 4)

# ⚠ ORDER. `mode: exclusive` takes the FIRST matching arc. If the save arc came first,
# `validate_input.ok` would match for a read too and every read would still write — the
# original defect, reintroduced by a reordering that looks harmless.
first = arcs[0]
# Through `begin_read`, not straight to load_profile: a sibling named here is SKIPPED when
# the save arc wins, and save_profile -> load_profile would then be dropped (every save
# strands). See scripts/playbook_skip_topology_test.py.
check("first arc targets begin_read", first.get("step"), "begin_read")
check(
    "first arc is guarded by read_only",
    "read_only" in (first.get("when") or ""),
    True,
)
check("second arc targets delete_profile", arcs[1].get("step"), "delete_profile")
check("third arc targets save_profile", arcs[2].get("step"), "save_profile")
check("fallback arc targets reject_input", arcs[-1].get("step"), "reject_input")
check("fallback arc is unguarded", arcs[-1].get("when") is None, True)

save_idx = next(i for i, a in enumerate(arcs) if a.get("step") == "save_profile")
read_idx = next(i for i, a in enumerate(arcs) if a.get("step") == "begin_read")
check("the read arc precedes the save arc", read_idx < save_idx, True)
check("load_profile is NOT an alternative at validate_input",
      "load_profile" in [a.get("step") for a in arcs], False)
begin = next((s for s in doc["workflow"] if s.get("step") == "begin_read"), {})
check("begin_read routes only to load_profile",
      [a.get("step") for a in (begin.get("next") or {}).get("arcs", [])], ["load_profile"])
save_step = next(s for s in doc["workflow"] if s.get("step") == "save_profile")
check("save_profile still routes to load_profile (read-after-write)",
      [a.get("step") for a in save_step["next"]["arcs"]], ["load_profile"])


# ------------------------------------------------------- the write is still a merge
print("\nthe save path is unchanged:")
save = next(s for s in doc["workflow"] if s.get("step") == "save_profile")
args = save["tool"]["payload"]["arguments"]
check("save_profile still uses set_doc", save["tool"]["payload"]["tool"], "set_doc")
# The issue is explicit: "Do not remove `merge: true`." Without it a partial save would
# erase every field the SPA did not send.
check("merge: true preserved", args.get("merge"), True)


# --------------------------------------------------------- the response tells truth
print("\nthe response does not claim a write that did not happen:")
build = next(s for s in doc["workflow"] if s.get("step") == "build_response")
bcode = build["tool"]["code"]
check("`saved` is derived from read_only", '"saved": (not _read_only)' in bcode, True)
check(
    "`found_after_write` is False on a read",
    '"found_after_write": (False if _read_only else found)' in bcode,
    True,
)
# Kept rather than dropped: existing consumers read it. The issue says so explicitly.
check("`found_after_write` key retained", "found_after_write" in bcode, True)


# -------------------------------------------------------------------- the workload
print("\nthe workload declares the flag:")
check("workload.read_only declared", "read_only" in doc["workload"], True)
check("workload.read_only defaults to False", doc["workload"].get("read_only"), False)
check(
    "validate_input binds read_only",
    "read_only" in (validate["tool"].get("input") or {}),
    True,
)


# ⚠ Print the denominator. "0 failures" over 0 checks is the same output as a healthy
# run, so the count of checks performed is part of the result.
print("\n%d check(s) performed, %d failure(s)" % (checks, len(failures)))
if checks < 25:
    print("FAIL: only %d checks ran — this guard is measuring less than it claims" % checks)
    sys.exit(1)
if failures:
    print("FAILED:")
    for f in failures:
        print("  - %s" % f)
    sys.exit(1)
print("OK")
