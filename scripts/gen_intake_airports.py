#!/usr/bin/env python3
"""Print the trip-intake airport tables from adiona/frontend's airport data.

The intake playbook may only return airport codes the FlightSearchForm can prefill
(`getAirportByCode` looks them up in src/data/airports.ts and moreAirports.ts), so
its tables are generated from the same files. Refresh them when either changes:

  python3 scripts/gen_intake_airports.py ../adiona/src/data major > major.txt
  python3 scripts/gen_intake_airports.py ../adiona/src/data more > more.txt

`major` is AIRPORTS (code|name|city|region|country|lat|lon), pasted over the
AIRPORTS block in playbooks/trip-intake.yaml. `more` is MORE_AIRPORTS without
names and with coordinates to 2 decimals (code|city|region|country|lat|lon|size),
zlib-compressed and base64-encoded to keep the step small, pasted over the
MORE_AIRPORTS block.
"""
import base64
import re
import sys
import zlib

MAJOR = re.compile(
    r"code: '([A-Z]{3})', name: (?:'([^']*)'|\"([^\"]*)\"), city: '([^']*)', country: '([^']*)', "
    r"lat: (-?[\d.]+), lon: (-?[\d.]+)(?:, region: '((?:[^'\\]|\\.)*)')?")

data, which = sys.argv[1], sys.argv[2]
if which == "major":
    rows = MAJOR.findall(open(data + "/airports.ts", encoding="utf-8").read())
    if len(rows) < 100:
        sys.exit("parsed only %d airports; the airports.ts format changed" % len(rows))
    for code, name1, name2, city, country, lat, lon, region in rows:
        print("            %s|%s|%s|%s|%s|%s|%s" % (code, name1 or name2, city, region.replace("\\'", "'"),
                                                    country, lat, lon))
elif which == "more":
    src = open(data + "/moreAirports.ts", encoding="utf-8").read()
    countries = dict(re.findall(r"^    ([A-Z0-9]{2}): '((?:[^'\\]|\\.)*)',$", src, re.M))
    body = src.split("const ROWS = `", 1)[1].split("`", 1)[0].strip().splitlines()
    if len(body) < 1000:
        sys.exit("parsed only %d airports; the moreAirports.ts format changed" % len(body))
    lines = []
    for row in body:
        code, _name, city, region, cc, lat, lon, size = row.split("|")
        lines.append("%s|%s|%s|%s|%.2f|%.2f|%s" % (code, city, region, countries.get(cc, cc).replace("\\'", "'"),
                                                   float(lat), float(lon), size))
    blob = base64.b64encode(zlib.compress("\n".join(lines).encode("utf-8"), 9)).decode("ascii")
    for i in range(0, len(blob), 100):
        print("            " + blob[i:i + 100])
else:
    sys.exit("usage: gen_intake_airports.py <adiona src/data> major|more")
