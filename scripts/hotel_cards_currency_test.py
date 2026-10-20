#!/usr/bin/env python3
"""playbooks/hotel-cards.yaml: every card and room says its currency (adiona/frontend#62
item 4). Runs map_cards' own embedded code offline (no HotelBeds).

HotelBeds states one ISO 4217 currency per hotel. The card's `price` string shows a
symbol only for USD, EUR and GBP ("$220"); any other currency became a bare
"220 CHF", and the numbers (pricePerNight, totalPrice) carried no currency at all.
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
             adults=2, children=0, max_rooms=10, price_bands=4)
    exec(steps["map_cards"]["tool"]["code"], g)
    return g["result"]


def hotel(code, currency):
    rate = {"rateKey": "k%s" % code, "net": "880.00", "roomName": "Double", "roomCode": "DBL",
            "boardName": "ROOM ONLY", "rateClass": "NOR"}
    h = {"code": code, "name": "Hotel %s" % code, "categoryCode": "4EST", "destinationName": "Zurich",
         "minRate": "880.00", "rates": [rate], "images": []}
    if currency:
        h["currency"] = currency
    return h


r = map_cards({"data": {"hotels": [hotel(1, "USD"), hotel(2, "CHF"), hotel(3, None)],
                        "meta": {"currency": "USD"}}})
usd, chf, unknown = r["hotels"]
check(usd["currency"] == "USD" and usd["price"] == "$220", "a USD hotel: currency USD, price $220")
check(chf["currency"] == "CHF" and chf["price"] == "220 CHF", "a CHF hotel says CHF, not just a bare number")
check(all(room["currency"] == card["currency"] for card in (usd, chf) for room in card["rooms"]) and chf["rooms"],
      "every room carries its hotel's currency")
check(unknown["currency"] is None and all(room["currency"] is None for room in unknown["rooms"]),
      "a hotel HotelBeds gave no currency for says none (null), never a guessed USD")
check(isinstance(usd["pricePerNight"], float) and usd["pricePerNight"] == 220.0,
      "amounts are unchanged; only the currency is added")

if failures:
    sys.exit("%d failure(s)" % len(failures))
