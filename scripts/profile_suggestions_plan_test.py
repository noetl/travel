#!/usr/bin/env python3
"""Guard: profile.yaml plans suggestions from the request OR the stored profile.

Before `plan_suggestions`, the Places step was guarded on the INPUT profile only. A login
read sends `profile: {}`, so the login response never carried suggestions, and saving a
section without coordinates skipped them even when the store held a home city.

Runs the playbook's OWN `plan_suggestions` code (no external calls) against the envelope
shape load_profile actually returns (MCP envelope -> get_doc data -> document.data).
"""
import sys

import yaml

PLAYBOOK = "playbooks/profile.yaml"
doc = yaml.safe_load(open(PLAYBOOK))
steps = {s["step"]: s for s in doc["workflow"]}

failures = []
checks = 0


def check(label, got, expect):
    global checks
    checks += 1
    ok = got == expect
    print("  %-62s expect=%-22r got=%-22r %s" % (label, expect, got, "OK" if ok else "FAIL"))
    if not ok:
        failures.append(label)


if "plan_suggestions" not in steps:
    print("FAIL: profile.yaml has no plan_suggestions step")
    sys.exit(1)
CODE = steps["plan_suggestions"]["tool"]["code"]


def plan(input_profile, stored):
    loaded = {"status": "ok", "data": {"found": stored is not None, "path": "users/qa-1",
                                       "document": None if stored is None else {"data": stored}}}
    ns = {"validated": {"ok": True, "profile": input_profile}, "loaded": loaded}
    exec(CODE, ns)
    return ns["result"]


LISBON = {"home_lat": 38.7223, "home_lng": -9.1393, "interests": ["museum", "restaurant"]}

print("where the coordinates come from:")
r = plan({}, LISBON)
check("login read ({}) uses the STORED coordinates", (r["has_coords"], r["coords_source"]), (True, "stored"))
check("...and the stored interests", r["interests"], ["museum", "restaurant"])
check("...first interest becomes includedType", r["included_type"], "museum")

r = plan({"home_lat": 48.85, "home_lng": 2.35}, LISBON)
check("request coordinates win over stored ones", (r["lat"], r["coords_source"]), (48.85, "input"))
check("interests fall back to stored when the request has none", r["interests"], ["museum", "restaurant"])

r = plan({"interests": ["spa"]}, LISBON)
check("request interests win over stored ones", r["interests"], ["spa"])

r = plan({"home_lat": None, "home_lng": None}, {})
check("explicit nulls and an empty store: no suggestions", r["has_coords"], False)
r = plan({}, None)
check("no stored document at all: no suggestions, no crash", r["has_coords"], False)
r = plan({"home_lat": True, "home_lng": 1}, {})
check("a bool is not a latitude", r["has_coords"], False)
r = plan({}, {"home_lat": 1.0})
check("half a coordinate pair is not coordinates", r["has_coords"], False)
check("no interests -> empty includedType (Places returns everything)", r["included_type"], "")

print("\nwiring:")
arcs = [(a.get("when"), a["step"]) for a in steps["plan_suggestions"]["next"]["arcs"]]
check("plan_suggestions routes on its own has_coords", arcs[0], ("{{ plan_suggestions.has_coords }}", "suggest_pois"))
check("...else skip_suggestions", arcs[1], (None, "skip_suggestions"))
check("load_profile routes only to plan_suggestions",
      [a["step"] for a in steps["load_profile"]["next"]["arcs"]], ["plan_suggestions"])
args = steps["suggest_pois"]["tool"]["payload"]["arguments"]
check("suggest_pois reads lat from the plan", args["lat"], "{{ plan_suggestions.lat }}")
check("suggest_pois reads lng from the plan", args["lng"], "{{ plan_suggestions.lng }}")
check("build_response binds the plan", "planned" in steps["build_response"]["tool"]["input"], True)
check("build_response no longer decides on the input's has_coords",
      'validated.get("has_coords")' in steps["build_response"]["tool"]["code"]
      or '_validated.get("has_coords")' in steps["build_response"]["tool"]["code"], False)

print("\n%d check(s) performed, %d failure(s)" % (checks, len(failures)))
if checks < 15:
    print("FAIL: fewer checks ran than this guard claims")
    sys.exit(1)
sys.exit(1 if failures else 0)
