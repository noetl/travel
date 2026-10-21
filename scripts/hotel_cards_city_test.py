#!/usr/bin/env python3
"""playbooks/hotel-cards.yaml: search by city NAME (adiona/frontend#62 items 1 and 3).

The frontend sends the city the traveller typed instead of coordinates from its own
hard-coded list. check_location finds the city in HotelBeds' records (our copy of their
hotel content, noetl/travel#166): the median of its hotels' coordinates is the search
centre; a name up to 40% off is corrected to the closest HotelBeds city without asking;
below that, "location not found". map_cards then keeps only hotels whose own city is the
requested one (no city on file: not shown; South San Francisco is not San Francisco).
Runs the steps' own code offline with Firestore stubbed.
"""
import io
import json
import sys
import urllib.request

import yaml

PLAYBOOK = "playbooks/hotel-cards.yaml"
failures = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


doc = yaml.safe_load(open(PLAYBOOK))
steps = {s["step"]: s for s in doc["workflow"]}


class Resp(io.BytesIO):
    def __init__(self, body):
        super().__init__(json.dumps(body).encode())
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def s(v):
    return {"stringValue": v}


def d(v):
    return {"doubleValue": v}


HOTELS = {  # city_key -> hotel rows as Firestore returns them
    "san francisco": [{"city": s("SAN FRANCISCO"), "countryCode": s("US"), "stateCode": s("CA"),
                       "lat": d(37.78 + i / 1000), "lng": d(-122.41 - i / 1000)} for i in range(5)],
    "portland": ([{"city": s("PORTLAND"), "countryCode": s("US"), "stateCode": s("OR"), "lat": d(45.52), "lng": d(-122.68)}] * 4
                 + [{"city": s("PORTLAND"), "countryCode": s("US"), "stateCode": s("ME"), "lat": d(43.66), "lng": d(-70.26)}] * 2),
    "paris": ([{"city": s("PARIS"), "countryCode": s("FR"), "lat": d(48.86), "lng": d(2.35)}] * 2
              + [{"city": s("PARIS"), "countryCode": s("US"), "stateCode": s("TX"), "lat": d(33.66), "lng": d(-95.55)}] * 3),
    "santiago": [{"city": s("SANTIAGO"), "countryCode": s("CL"), "lat": d(-33.45), "lng": d(-70.66)}],
    "nocoords": [{"city": s("NOCOORDS"), "countryCode": s("XX")}],
}
CITIES = {"sa": ["san francisco", "san jose", "santiago"], "po": ["portland", "porto"], "pa": ["paris", "palermo"]}
queries = []
FAIL = {}


def fake_urlopen(req, timeout=None):
    url = req.full_url
    if "metadata.google.internal" in url:
        return Resp({"access_token": "t"})
    assert url.endswith(":runQuery"), url
    if FAIL:
        raise OSError("firestore down")
    q = json.loads(req.data.decode())["structuredQuery"]
    queries.append(q)
    f = q["where"]["fieldFilter"]
    value = f["value"]["stringValue"]
    if q["from"][0]["collectionId"] == "hotelbeds_content":
        assert f["field"]["fieldPath"] == "city_key"
        return Resp([{"document": {"fields": row}} for row in HOTELS.get(value, [])] or [{"readTime": "x"}])
    assert q["from"][0]["collectionId"] == "hotelbeds_cities" and f["field"]["fieldPath"] == "prefix"
    return Resp([{"document": {"fields": {"city_key": s(c)}}} for c in CITIES.get(value, [])] or [{"readTime": "x"}])


urllib.request.urlopen = fake_urlopen


def locate(city="", latitude="", longitude=""):
    queries.clear()
    g = dict(city=city, latitude=latitude, longitude=longitude, google_project="proj", firestore_database="(default)")
    exec(steps["check_location"]["tool"]["code"], g)
    return g["result"]


r = locate("San Francisco")
check(r["location_ok"] and r["source"] == "hotelbeds_content" and r["city"] == "San Francisco" and not r["corrected"],
      "a city HotelBeds has is found in its records")
check(r["latitude"] == 37.782 and r["longitude"] == -122.412, "the search centre is the median of its hotels' coordinates")
check(queries[0]["from"][0]["collectionId"] == "hotelbeds_content" and queries[0]["where"]["fieldFilter"]["value"] == s("san francisco"),
      "it is looked up by city_key (case and accents ignored)")
r = locate("  SAN-FRANCISCO ")
check(r["location_ok"] and r["city_key"] == "san francisco" and not r["corrected"], "case, spaces and punctuation do not matter")

r = locate("San Fransisco")
check(r["location_ok"] and r["corrected"] and r["city"] == "San Francisco" and r["city_key"] == "san francisco"
      and r["match_score"] >= 0.6, "a typo is corrected to the closest HotelBeds city, without asking: %s" % r.get("match_score"))
check(any(q["from"][0]["collectionId"] == "hotelbeds_cities" and q["where"]["fieldFilter"]["value"] == s("sa") for q in queries),
      "candidates come from the city index by the name's first two letters")
r = locate("Santiaho")
check(r["location_ok"] and r["city_key"] == "santiago" and r["latitude"] == -33.45,
      "the closest match wins, not the first candidate")
r = locate("Satiwxyz")
check(not r["location_ok"] and r["code"] == "location_not_found",
      "50% alike to Santiago (which HotelBeds has) is still not a match: the bar is 60%")
r = locate("Saxtixgx")
check(r["location_ok"] and r["city_key"] == "santiago", "62% alike is a match")
r = locate("Sxntiago")
check(not r["location_ok"], "known limit: a typo in the first two letters is not matched (candidates share them)")
r = locate("Sanxyzqw")
check(not r["location_ok"] and r["code"] == "location_not_found" and "couldn't find a city called \"Sanxyzqw\"" in r["message"],
      "below 60% alike: location not found, said plainly")
r = locate("Qqqq")
check(not r["location_ok"] and r["code"] == "location_not_found", "no candidate at all: location not found")
r = locate("Nocoords")
check(not r["location_ok"] and r["code"] == "location_not_found", "a city whose hotels have no coordinates is not searched")

r = locate("Portland")
check(r["location_ok"] and r["latitude"] == 45.52, "a shared name without a qualifier takes the place with the most hotels")
r = locate("Portland, Maine")
check(r["location_ok"] and r["latitude"] == 43.66 and r["longitude"] == -70.26, "\"Portland, Maine\" is the one in Maine")
r = locate("Portland, OR")
check(r["latitude"] == 45.52, "a two-letter state works too")
r = locate("Paris, Texas")
check(r["latitude"] == 33.66, "\"Paris, Texas\" is not Paris, France")
r = locate("Paris, France")
check(r["latitude"] == 48.86 and r["countryCode"] == "FR", "a country name narrows it, even to the smaller place")
r = locate("Paris, FR")
check(r["latitude"] == 48.86, "a two-letter country code works too")
r = locate("Paris, Narnia")
check(r["location_ok"] and r["latitude"] == 33.66, "an unknown qualifier does not fail the search (most hotels)")

r = locate("San Francisco", latitude="41.9", longitude="12.5")
check(r["location_ok"] and r["source"] == "coordinates" and r["latitude"] == 41.9 and queries == [],
      "coordinates sent with the request are used as they are (no lookup)")
check(r["city_key"] == "san francisco", "...and the city still filters the results")
r = locate("San Francisco", latitude="41.9", longitude="")
check(r["location_ok"] and r["source"] == "hotelbeds_content", "a latitude alone is not coordinates: the city is looked up")
r = locate("")
check(not r["location_ok"] and r["code"] == "missing_location", "nothing sent: missing_location, as before")
FAIL["on"] = True
r = locate("San Francisco")
check(not r["location_ok"] and r["code"] == "location_lookup_failed" and "can't look up locations" in r["message"],
      "the lookup failing is said as such, and nothing is searched")
FAIL.clear()

# The flow: the search uses what check_location found; a failure says why.
args = steps["search_hotels"]["tool"]["payload"]["arguments"]
check(args["city"] == "{{ check_location.city }}" and args["latitude"] == "{{ check_location.latitude }}"
      and args["longitude"] == "{{ check_location.longitude }}", "the search uses the resolved city and coordinates")
g = dict(check_in="2026-11-03", check_out="2026-11-07",
         location={"location_ok": False, "code": "location_not_found", "message": "We couldn't find a city called \"X\"."})
exec(steps["no_location"]["tool"]["code"], g)
check(g["result"]["provider_error_code"] == "location_not_found" and g["result"]["provider_error"].startswith("We couldn't find"),
      "no_location returns the lookup's own reason")
wl = doc["workload"]
check(wl.get("google_project") and wl.get("firestore_database") == "(default)", "the playbook knows where the copy lives")

# map_cards: only hotels in the requested city.
def card_run(hotels, city_key):
    g = dict(search_result={"data": {"hotels": hotels}}, check_in="2026-11-03", check_out="2026-11-07",
             adults=2, children=0, max_rooms=10, price_bands=4, currencies=["USD"], city_key=city_key)
    exec(steps["map_cards"]["tool"]["code"], g)
    return g["result"]


def hotel(code, city):
    h = {"code": code, "name": "H%s" % code, "currency": "USD", "minRate": "400.00", "categoryCode": "3EST",
         "rates": [{"rateKey": "k", "net": "400.00", "roomCode": "DBL", "roomName": "Double", "rateClass": "NOR"}]}
    if city is not None:
        h["city"] = city
    return h


r = card_run([hotel(1, "SAN FRANCISCO"), hotel(2, "OAKLAND"), hotel(3, "SOUTH SAN FRANCISCO"), hotel(4, None),
              hotel(5, "San Francisco"), hotel(6, "San  Francisco, ")], "san francisco")
check([c["id"] for c in r["hotels"]] == ["h1", "h5", "h6"], "only hotels in San Francisco itself: %s" % [c["id"] for c in r["hotels"]])
check(r["excluded_by_city"] == {"other_city": 2, "no_city": 1} and r["city_filter"] == "san francisco",
      "Oakland and South San Francisco are other cities; a hotel with no city on file is not shown")
r = card_run([hotel(1, "SAN FRANCISCO"), hotel(2, None)], "")
check([c["id"] for c in r["hotels"]] == ["h1", "h2"] and r["city_filter"] is None, "no city asked: no city filter")

if failures:
    sys.exit("%d failure(s)" % len(failures))
