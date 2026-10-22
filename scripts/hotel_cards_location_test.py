#!/usr/bin/env python3
"""playbooks/hotel-cards.yaml: no default location (adiona/frontend#62 item 1).

A search the caller did not place used to run against Monterey, California (the
workload default), so a city the frontend could not geocode silently returned
Monterey hotels. Now `check_location` routes it to `no_location`, which says so
without calling HotelBeds. Runs the steps' own code offline.
"""
import sys

import yaml

PLAYBOOK = "playbooks/hotel-cards.yaml"
failures = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


doc = yaml.safe_load(open(PLAYBOOK))
steps = {s["step"]: s for s in doc["workflow"]}
wl = doc["workload"]


def run(step, **inputs):
    g = dict(inputs)
    exec(steps[step]["tool"]["code"], g)
    return g["result"]


check(wl.get("city") in ("", None) and wl.get("latitude") in ("", None) and wl.get("longitude") in ("", None),
      "the workload carries no default location")
check("monterey" not in yaml.safe_dump(wl).lower(), "Monterey is gone from the defaults")

for label, inp, ok in [
    ("coordinates", dict(city="", latitude="41.9", longitude="12.5"), True),
    ("coordinates as numbers", dict(city="", latitude=41.9, longitude=12.5), True),
    ("a city name", dict(city="Rome", latitude="", longitude=""), True),
    ("nothing", dict(city="", latitude="", longitude=""), False),
    ("blank city", dict(city="   ", latitude="", longitude=""), False),
    ("only a latitude", dict(city="", latitude="41.9", longitude=""), False),
    ("out-of-range coordinates", dict(city="", latitude="123", longitude="12.5"), False),
    ("non-numeric coordinates", dict(city="", latitude="north", longitude="east"), False),
]:
    r = run("check_location", **inp)
    check(r["location_ok"] is ok, "%s -> location_ok=%s" % (label, ok))

arcs = steps["check_location"]["next"]["arcs"]
check(arcs[0].get("step") == "search_hotels" and "location_ok" in arcs[0].get("when", "")
      and arcs[1].get("step") == "no_location" and "when" not in arcs[1],
      "a placed search goes to search_hotels; anything else to no_location")
check(steps["resolve_dates"]["next"]["arcs"][0]["step"] == "check_location",
      "the location is checked before any HotelBeds call")

nl = run("no_location", check_in="2026-11-03", check_out="2026-11-07",
         location=run("check_location", city="", latitude="", longitude=""))
check(nl["hotels"] == [] and nl["count"] == 0, "no location: no hotels")
check(nl["provider_error_code"] == "missing_location" and "No location received" in nl["provider_error"],
      "no location: says so, readably")
check(steps["no_location"]["next"]["arcs"][0]["step"] == "final_result", "no_location ends at final_result")
nl_code = steps["no_location"]["tool"]["code"]
check(steps["no_location"]["tool"]["kind"] == "python" and "path" not in steps["no_location"]["tool"]
      and not any(k in nl_code for k in ("urllib", "requests", "http.client", "socket")),
      "no_location calls no provider (a plain python step, no child playbook, no network)")

fr = run("final_result", mapped={}, no_location=nl)
check(fr is nl, "final_result returns the no-location result when the search was skipped")
cards = {"hotels": [{"id": "h1"}], "count": 1, "provider_error": None}
check(run("final_result", mapped=cards, no_location={}) is cards, "final_result returns the cards when the search ran")

if failures:
    sys.exit("%d failure(s)" % len(failures))
