#!/usr/bin/env python3
"""Print trip-intake's known-places table from data/intake_places.yaml.

  python3 scripts/gen_intake_places.py ../adiona/src/data > places.txt

and paste the output over the PLACES block in playbooks/trip-intake.yaml. Fails if an
airport code is not in adiona's airport list (the flight form could not prefill it),
if a region names an island that is not listed, or if one name is given to two places.
"""
import re
import sys
import unicodedata

import yaml


def norm(text):
    low = unicodedata.normalize("NFD", str(text)).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(re.sub(r"[-.']", " ", low).split())


data = yaml.safe_load(open("data/intake_places.yaml", encoding="utf-8"))
src = sys.argv[1]
codes = set(re.findall(r"code: '([A-Z]{3})'", open(src + "/airports.ts", encoding="utf-8").read()))
codes |= set(re.findall(r"^([A-Z]{3})\|", open(src + "/moreAirports.ts", encoding="utf-8").read(), re.M))
seen, problems, lines = {}, [], []
for island in data["islands"]:
    for code in island["airports"]:
        if code not in codes:
            problems.append("%s: %s is not in the airport list" % (island["name"], code))
    if not island["airports"] and ("lat" not in island or "lon" not in island):
        problems.append("%s: no airport and no coordinates" % island["name"])
    for name in [island["name"]] + island.get("aliases", []):
        if seen.get(norm(name), island["name"]) != island["name"]:
            problems.append("%s names two places" % name)
        seen[norm(name)] = island["name"]
    lines.append("island|%s|%s|%s|%s|%s|%s" % (island["name"], ";".join(island.get("aliases", [])), island["country"],
                                               ",".join(island["airports"]), island["lat"], island["lon"]))
islands = {i["name"] for i in data["islands"]}
for region in data["regions"]:
    for name in region["islands"]:
        if name not in islands:
            problems.append("%s: island %s is not listed" % (region["name"], name))
    for name in [region["name"]] + region.get("aliases", []):
        if seen.get(norm(name), region["name"]) != region["name"]:
            problems.append("%s names two places" % name)
        seen[norm(name)] = region["name"]
    lines.append("region|%s|%s|%s" % (region["name"], ";".join(region.get("aliases", [])), ",".join(region["islands"])))
if problems:
    sys.exit("\n".join(problems))
for line in lines:
    print("            " + line)
