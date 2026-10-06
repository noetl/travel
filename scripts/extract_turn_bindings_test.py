#!/usr/bin/env python3
"""Every name a playbook step BINDS must be supplied by the harnesses that exec its code.

adiona/frontend#59.

# Why this exists

The planner harnesses exec `extract_turn`'s embedded `code:` directly, with a hand-built
globals dict standing in for the playbook's `input:` bindings. That is the right technique
— it runs the real code with no external calls — but it duplicates a list, and the two
copies drift.

They did. Eight bindings were added to the playbook after the harnesses were written
(`llm_extraction_enabled`, `default_origin`, `vertex_project`, `vertex_region`,
`slm_backend`, `slm_endpoint`, `slm_model`, `slm_api_key`), and **both** planner tests
began dying on:

    NameError: name 'llm_extraction_enabled' is not defined

⚠⚠ Nobody noticed, because **nothing ran them**. `grep` across the repo found **0**
invocations of any `scripts/*_test.py`. Two regression guards sat broken, asserting
nothing, while reporting nothing — the failure mode where a guard and its absence are
indistinguishable.

So the fix is two-part: the harnesses are repaired, and this guard makes the next added
binding fail *here*, loudly, instead of rotting. The CI workflow that runs it is the other
half; a guard with no runner is what created this situation.
"""
import re
import sys

import yaml

PLAYBOOK = "playbooks/itinerary-planner.yaml"
STEP = "extract_turn"

# Harnesses that exec this step's code and therefore must mirror its bindings.
HARNESSES = [
    "scripts/planner_flow_advance_test.py",
    "scripts/planner_restate_routing_test.py",
]

doc = yaml.safe_load(open(PLAYBOOK))
step = next(s for s in doc["workflow"] if s.get("step") == STEP)
bound = set((step["tool"].get("input") or {}).keys())

# ⚠ Assert the extraction before asserting about it. An empty bound-set would make every
# harness look complete, which is the same output as a healthy repo.
print("playbook %s step %s binds %d name(s)" % (PLAYBOOK, STEP, len(bound)))
if len(bound) < 10:
    print(
        "FAIL: only %d bindings parsed from the playbook — the extraction is wrong, so "
        "any 'complete' verdict below would be meaningless" % len(bound)
    )
    sys.exit(1)

failures = []
for h in HARNESSES:
    try:
        src = open(h).read()
    except OSError as e:
        failures.append("%s: cannot read (%s)" % (h, e))
        continue

    # The harness builds its globals as a dict literal of "name": value pairs. Collect
    # every quoted key it assigns anywhere, which over-counts rather than under-counts —
    # the safe direction, since a false "missing" is noisy but a false "present" is the
    # bug this guard exists to catch.
    supplied = set(re.findall(r'"(\w+)"\s*:', src))
    missing = sorted(bound - supplied)
    print(
        "  %-46s supplies %3d name(s), missing %d"
        % (h, len(supplied), len(missing))
    )
    if missing:
        failures.append(
            "%s does not supply: %s" % (h, ", ".join(missing))
        )

print()
if failures:
    print("FAILED — a harness exec'ing %s will raise NameError at runtime:" % STEP)
    for f in failures:
        print("  - %s" % f)
    print()
    print(
        "Add the missing name(s) to the harness globals, using the playbook's own\n"
        "`| default(...)` value so the harness mirrors production rather than guessing."
    )
    sys.exit(1)
print("OK — every binding is supplied by every harness")
