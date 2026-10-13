#!/usr/bin/env python3
"""Every widget payload the planner builds must satisfy that widget's schema.

The SPA validates each envelope's payload against
playbooks/widget-contract/<widget_type>.schema.json before rendering. A payload
missing a required property, or carrying one the schema does not declare
(`additionalProperties: false`), is not rendered at all -- the user sees
"Unable to render this response (template mismatch)" instead of the card.

This guard parses itinerary-planner's `render_widget_chat` code and checks every
`_env("<widget_type>", <variant>, {literal payload})` call: each required key is
present and no key is outside the schema's `properties`. Keys added to the dict
later (subscript assignment) are not seen; literal payloads are the common case.

Regression: prod execution 368219441512587264 (2026-10-13) -- the "No matching
flights" error_card carried `message` / `reason_code` / `alternatives` / `ctas` /
`blocking_constraints` and no `description`, so the booking flow showed a
template-mismatch error instead of the card.
"""
import ast
import json
import os
import sys

import yaml

PLAYBOOK = "playbooks/itinerary-planner.yaml"
CONTRACT = "playbooks/widget-contract"
STEP = "render_widget_chat"

doc = yaml.safe_load(open(PLAYBOOK))
code = next(s for s in doc["workflow"] if s.get("step") == STEP)["tool"]["code"]
tree = ast.parse(code)

calls = []
for node in ast.walk(tree):
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_env"
            and len(node.args) >= 3 and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[2], ast.Dict)):
        keys = [k.value for k in node.args[2].keys if isinstance(k, ast.Constant)]
        spread = any(k is None for k in node.args[2].keys)  # {**other}: keys unknown
        calls.append((node.args[0].value, node.lineno, keys, spread))

print("literal _env payloads found: %d" % len(calls))
if len(calls) < 10:
    print("FAIL: too few _env calls parsed -- the extraction is wrong, so a pass would mean nothing")
    sys.exit(1)

failures = []
checked = 0
for widget, line, keys, spread in calls:
    path = os.path.join(CONTRACT, widget + ".schema.json")
    if not os.path.exists(path):
        failures.append("%s (code line %d): no schema %s" % (widget, line, path))
        continue
    schema = json.load(open(path))
    props = set((schema.get("properties") or {}).keys())
    required = set(schema.get("required") or [])
    missing = sorted(required - set(keys)) if not spread else []
    extra = sorted(set(keys) - props) if schema.get("additionalProperties") is False else []
    checked += 1
    if missing or extra:
        failures.append("%s (code line %d): missing %s, not allowed %s" % (widget, line, missing, extra))

for f in failures:
    print("FAIL " + f)
print("---\npayloads checked: %d   failures: %d" % (checked, len(failures)))
sys.exit(1 if failures else 0)
