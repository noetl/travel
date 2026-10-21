#!/usr/bin/env python3
"""playbooks/hotel-cards.yaml: rooms say how many are left and until when cancelling is
free (adiona/frontend#95). Both come from HotelBeds availability fields the provider
already passes through: a rate's `allotment` ("number of rooms available for a
particular room type") and its `cancellationPolicies[].from`. Offline, map_cards' code.
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


def rate(key, net, **kw):
    return dict({"rateKey": key, "net": net, "roomName": "Double", "roomCode": "DBL",
                 "boardName": "ROOM ONLY", "rateClass": "NOR"}, **kw)


rates = [
    rate("a", "400.00", allotment=3, cancellationPolicies=[
        {"amount": "200.00", "from": "2026-11-01T23:59:00+01:00"},
        {"amount": "100.00", "from": "2026-10-30T23:59:00+01:00"}]),
    rate("b", "380.00", rateClass="NRF", allotment="2",
         cancellationPolicies=[{"amount": "380.00", "from": "2026-10-20T00:00:00+01:00"}]),
    rate("c", "500.00"),
    rate("d", "510.00", allotment=-1),
]
r = map_cards({"data": {"hotels": [{"code": 7, "name": "Hotel 7", "categoryCode": "4EST", "currency": "EUR",
                                    "minRate": "380.00", "rates": rates, "images": []}]}})
rooms = {room["rate_key"]: room for room in r["hotels"][0]["rooms"]}
check(rooms["a"]["roomsLeft"] == 3 and rooms["b"]["roomsLeft"] == 2, "roomsLeft is HotelBeds' allotment (number or numeric string)")
check(rooms["c"]["roomsLeft"] is None, "no allotment: roomsLeft is null, not a guess")
check(rooms["d"]["roomsLeft"] is None, "a negative allotment is not a room count: null")
check(rooms["a"]["freeCancellationUntil"] == "2026-10-30T23:59:00+01:00",
      "freeCancellationUntil is the earliest charge date, as HotelBeds gave it")
check(rooms["b"]["freeCancellationUntil"] is None, "a non-refundable rate has no free cancellation")
check(rooms["c"]["freeCancellationUntil"] is None, "no policy: null, not a guess")

if failures:
    sys.exit("%d failure(s)" % len(failures))
