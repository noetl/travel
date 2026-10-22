#!/usr/bin/env python3
"""Print hotel-cards' city table (interim city-name lookup) from adiona's airport data.

  python3 scripts/gen_hotel_cards_cities.py ../adiona/src/data > cities.txt

One row per airport with scheduled service (adiona src/data/airports.ts and
moreAirports.ts): town|region|country|lat|lon|major|large, zlib-compressed and
base64-encoded, pasted over the CITIES block of playbooks/hotel-cards.yaml.
hotel-cards uses it to place a city sent by NAME (no coordinates) until the search
can use HotelBeds' own records (noetl/travel#166, #171).
"""
import base64
import re
import sys
import zlib

src = sys.argv[1]
ts = open(src + "/airports.ts", encoding="utf-8").read()
more = open(src + "/moreAirports.ts", encoding="utf-8").read()
countries = dict(re.findall(r"^    ([A-Z0-9]{2}): '((?:[^'\\]|\\.)*)',$", more, re.M))
rows = []
for m in re.finditer(r"code: '([A-Z]{3})', name: (?:'[^']*'|\"[^\"]*\"), city: '([^']*)', country: '([^']*)', "
                     r"lat: (-?[\d.]+), lon: (-?[\d.]+)(?:, region: '((?:[^'\\]|\\.)*)')?", ts):
    code, city, country, lat, lon, region = m.groups()
    rows.append("%s|%s|%s|%.3f|%.3f|1|1" % (city, region.replace("\\'", "'"), country, float(lat), float(lon)))
body = more.split("const ROWS = `", 1)[1].split("`", 1)[0].strip().splitlines()
for row in body:
    code, _name, city, region, cc, lat, lon, size = row.split("|")
    rows.append("%s|%s|%s|%.3f|%.3f|0|%d" % (city, region, countries.get(cc, cc).replace("\\'", "'"),
                                             float(lat), float(lon), size == "L"))
if len(rows) < 3000:
    sys.exit("parsed only %d airports; the adiona airport files changed" % len(rows))
blob = base64.b64encode(zlib.compress("\n".join(rows).encode("utf-8"), 9)).decode("ascii")
for i in range(0, len(blob), 100):
    print("            " + blob[i:i + 100])
