#!/usr/bin/env python3
"""Print the trip-intake airport table from adiona/frontend's src/data/airports.ts.

The intake playbook may only return airport codes the FlightSearchForm can prefill
(`getAirportByCode` looks them up in that file), so its table is generated from the
same list. Refresh it when airports.ts changes:

  python3 scripts/gen_intake_airports.py ../adiona/src/data/airports.ts

and paste the output over the AIRPORTS block in playbooks/trip-intake.yaml.
"""
import re
import sys

ROW = re.compile(
    r"code: '([A-Z]{3})', name: (?:'([^']*)'|\"([^\"]*)\"), city: '([^']*)', country: '([^']*)', "
    r"lat: (-?[\d.]+), lon: (-?[\d.]+)")

rows = ROW.findall(open(sys.argv[1]).read())
if len(rows) < 100:
    sys.exit("parsed only %d airports; the airports.ts format changed" % len(rows))
for code, name1, name2, city, country, lat, lon in rows:
    print("            %s|%s|%s|%s|%s|%s" % (code, name1 or name2, city, country, lat, lon))
