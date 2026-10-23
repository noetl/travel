#!/usr/bin/env python3
"""playbooks/hotel-cards.yaml (interim v12): a city sent by NAME is placed with the
airport table (adiona/frontend#62), until the search can use HotelBeds' own records
(noetl/travel#166, #171). Before this, only Paris, Miami, Boston, New York and London
resolved (the provider's hard-coded fallback); Tbilisi came back "could not resolve a
geolocation". Runs check_location's own code offline.
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


def locate(city="", latitude="", longitude="", radius=20):
    g = dict(city=city, latitude=latitude, longitude=longitude, radius=radius)
    exec(steps["check_location"]["tool"]["code"], g)
    return g["result"]


def near(r, lat, lon, km):
    import math
    p1, p2 = math.radians(r["latitude"]), math.radians(lat)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon - r["longitude"]) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h)) <= km


lib = {"city": "", "latitude": "", "longitude": ""}
exec(steps["check_location"]["tool"]["code"], lib)
check(sum(len(v) for v in lib["TOWNS"].values()) > 3000, "the airport table is built in (%d town entries)" % len(lib["TOWNS"]))

r = locate("Tbilisi")
check(r["location_ok"] and r["source"] == "airport_table" and near(r, 41.7151, 44.8271, 25),
      "Tbilisi (failed before) is placed near Tbilisi: %s, %s" % (r.get("latitude"), r.get("longitude")))
check(r["radius"] == 30, "placed by its airport, the radius is at least 30 km")
r = locate("Rome")
check(r["location_ok"] and near(r, 41.9028, 12.4964, 25), "Rome: the mean of its airports, near the centre")
r = locate("Stockholm")
check(r["latitude"] == round((59.652 + 59.354) / 2, 4) and r["longitude"] == round((17.919 + 17.942) / 2, 4),
      "Stockholm: Arlanda and Bromma (33 km apart, one place) are averaged")
r = locate("Karpathos")
check(r["location_ok"] and r["source"] == "airport_table", "an \"X Island\" airport town answers to X (Karpathos)")
r = locate("Tbilisi", latitude="41.9", longitude="")
check(r["source"] == "airport_table", "a latitude alone is not coordinates: the city is looked up")
r = locate("Paris")
check(r["source"] == "city_centre" and r["latitude"] == 48.8566 and r["longitude"] == 2.3522 and r["radius"] == 20,
      "Paris keeps its exact centre and the requested radius (as before)")
for name in ("London", "New York", "Miami", "Boston"):
    check(locate(name)["source"] == "city_centre", "%s keeps its exact centre" % name)
r = locate("Portland")
check(near(r, 45.59, -122.60, 30), "Portland without a qualifier: the one with a major airport (Oregon)")
r = locate("Portland, Maine")
check(near(r, 43.65, -70.31, 30) and r["region"] == "Maine", "\"Portland, Maine\" is the one in Maine")
r = locate("Paris, Texas")
check(r["source"] == "airport_table", "a qualified Paris goes through the table, not Paris, France's centre")
r = locate("Kauai")
check(r["location_ok"] and near(r, 21.97, -159.34, 10), "an island the table names (\"Lihue, Kauai\") is placed")
r = locate("  san francisco ")
check(r["location_ok"] and near(r, 37.62, -122.38, 20), "case and spaces do not matter")

r = locate("Tbilissi")
check(not r["location_ok"] and r["code"] == "location_not_found",
      "no typo correction in the interim: a misspelling is 'location not found' (trip-intake corrects spelling first)")
r = locate("Xqzzyplov")
check(not r["location_ok"] and r["code"] == "location_not_found" and "couldn't find a city called \"Xqzzyplov\"" in r["message"],
      "an unknown name: location not found")
r = locate("Napa")
check(not r["location_ok"] and r["code"] == "location_not_found",
      "known limit: a town without an airport (Napa) is not found, and is never turned into Naha, Okinawa")

r = locate("Tbilisi", latitude="41.9", longitude="12.5", radius=15)
check(r["source"] == "coordinates" and r["latitude"] == 41.9 and r["radius"] == 15, "coordinates sent with the request win")
r = locate("Tbilisi", radius=60)
check(r["radius"] == 60, "a larger requested radius is kept")
r = locate("Tbilisi", radius="bogus")
check(r["radius"] == 30, "a bad radius falls back to the default, widened for an airport")
r = locate("")
check(not r["location_ok"] and r["code"] == "missing_location", "nothing sent: missing_location, as before")

args = steps["search_hotels"]["tool"]["payload"]["arguments"]
check(args["latitude"] == "{{ check_location.latitude }}" and args["longitude"] == "{{ check_location.longitude }}"
      and args["radius"] == "{{ check_location.radius }}" and args["city"] == "{{ check_location.city }}",
      "the search uses what check_location placed")
check("radius" in steps["check_location"]["tool"]["input"], "check_location gets the requested radius")
g = dict(check_in="2026-11-03", check_out="2026-11-07", location=locate("Xqzzyplov"))
exec(steps["no_location"]["tool"]["code"], g)
check(g["result"]["provider_error_code"] == "location_not_found" and g["result"]["hotels"] == [],
      "no_location returns the lookup's own reason")
src = open(PLAYBOOK).read()
check("EUR" in (doc["workload"].get("currencies") or ["EUR"]) and "hotelbeds_content" not in src and "firestore.googleapis" not in src,
      "interim: no USD-only rule (EUR still allowed while the account prices in EUR) and no HotelBeds-content dependency")

if failures:
    sys.exit("%d failure(s)" % len(failures))
