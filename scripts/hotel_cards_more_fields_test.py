#!/usr/bin/env python3
"""playbooks/hotel-cards.yaml: fields adiona/frontend#95 asks for that HotelBeds'
availability search already returns (no hotel-content call; see noetl/travel#166):
the hotel's coordinates and zone, and each rate's payment type, promotions and offers.
Runs map_cards' own embedded code offline.
"""
import sys

import yaml

PLAYBOOK = "playbooks/hotel-cards.yaml"
failures = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


steps = {s["step"]: s for s in yaml.safe_load(open(PLAYBOOK))["workflow"]}


def map_cards(search_result):
    g = dict(search_result=search_result, check_in="2026-11-03", check_out="2026-11-07",
             adults=2, children=0, max_rooms=10, price_bands=4, currencies=["EUR"])
    exec(steps["map_cards"]["tool"]["code"], g)
    return g["result"]


rate_a = {"rateKey": "a", "net": "400.00", "roomName": "Double", "roomCode": "DBL", "boardName": "ROOM ONLY",
          "rateClass": "NOR", "paymentType": "AT_WEB",
          "promotions": [{"code": "EB", "name": "Early booking", "remark": "Book 30 days ahead"}, {}],
          "offers": [{"code": "1100", "name": "Early Booking Discount", "amount": "-40.00"}]}
rate_b = {"rateKey": "b", "net": "450.00", "roomName": "Double", "roomCode": "DBL", "boardName": "BED AND BREAKFAST",
          "rateClass": "NOR"}
full = {"code": 1, "name": "Hotel 1", "categoryCode": "4EST", "currency": "EUR", "minRate": "400.00",
        "destinationName": "Paris", "zoneName": "Le Marais", "latitude": "48.8590", "longitude": "2.3620",
        "rates": [rate_a, rate_b], "images": []}
bare = {"code": 2, "name": "Hotel 2", "categoryCode": "3EST", "currency": "EUR", "minRate": "300.00",
        "latitude": "999", "longitude": "2.3", "rates": [dict(rate_b, rateKey="c")], "images": []}
r = map_cards({"data": {"hotels": [full, bare]}})
h1, h2 = r["hotels"]
check(h1["coordinates"] == {"lat": 48.859, "lng": 2.362}, "coordinates are the hotel's, as numbers {lat, lng}")
check(h2["coordinates"] is None, "out-of-range coordinates: null, never a wrong pin")
check(h1["neighborhood"] == "Le Marais" and h2["neighborhood"] is None, "neighborhood is HotelBeds' zone; null when absent")
rooms = {room["rate_key"]: room for room in h1["rooms"]}
check(rooms["a"]["paymentType"] == "AT_WEB" and rooms["b"]["paymentType"] is None,
      "paymentType is passed on unchanged; null when absent")
check(rooms["a"]["promotions"] == [{"code": "EB", "name": "Early booking", "remark": "Book 30 days ahead"}],
      "promotions keep code, name and remark; empty entries are dropped")
check(rooms["a"]["offers"] == [{"code": "1100", "name": "Early Booking Discount", "amount": -40.0}],
      "offers keep code, name and the amount as a number")
check(rooms["b"]["promotions"] == [] and rooms["b"]["offers"] == [], "a rate without any: empty lists")
check(h1["location"] == "Paris" and h1["pricePerNight"] == [{"currency": "EUR", "price": 100.0}], "existing fields are unchanged")

if failures:
    sys.exit("%d failure(s)" % len(failures))
