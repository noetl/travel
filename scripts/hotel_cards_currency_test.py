#!/usr/bin/env python3
"""playbooks/hotel-cards.yaml: prices come only in the allowed currencies, as
pricePerNight: [{currency, price}] (adiona/frontend#62 item 4). Runs map_cards' own
embedded code offline (no HotelBeds).

HotelBeds prices every hotel in the account's currency (one per hotel). We return only
the currencies in workload.currencies (default USD) and never convert: a hotel priced in
another currency is left out, counted in excluded_by_currency, and when that leaves
nothing the result says why instead of looking like "no hotels".
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


def map_cards(search_result, **kw):
    g = dict(search_result=search_result, check_in="2026-11-03", check_out="2026-11-07",
             adults=2, children=0, max_rooms=10, price_bands=4)
    g.update(kw)
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


check(doc["workload"].get("currencies") == ["USD", "EUR"]
      and "default(['USD', 'EUR'])" in steps["map_cards"]["tool"]["input"].get("currencies", ""),
      "interim: USD and EUR are allowed (the TEST account prices in EUR), passed to map_cards")

SEARCH = {"data": {"hotels": [hotel(1, "USD"), hotel(2, "CHF"), hotel(3, None), hotel(4, "usd")]}}
r = map_cards(SEARCH)
ids = [c["id"] for c in r["hotels"]]
check(ids == ["h1", "h4"], "only USD-priced hotels are returned: %s" % ids)
usd = r["hotels"][0]
check(usd["pricePerNight"] == [{"currency": "USD", "price": 220.0}], "pricePerNight is [{currency, price}]")
check(all(room["pricePerNight"] == [{"currency": "USD", "price": 220.0}] for room in usd["rooms"]) and usd["rooms"],
      "each room's pricePerNight has the same shape")
check(usd["currency"] == "USD" and "price" not in usd and all("price" not in room for room in usd["rooms"]),
      "no display `price` on the card or its rooms (adiona/frontend#95): pricePerNight only")
check(r["excluded_by_currency"] == {"CHF": 1, "NONE": 1} and r["currencies"] == ["USD"],
      "hotels left out for their currency are counted: %s" % r["excluded_by_currency"])
check(r["provider_error"] is None, "no error when some hotels remain")

r = map_cards({"data": {"hotels": [hotel(1, "EUR"), hotel(2, "EUR")]}})
check(r["hotels"] == [] and r["provider_error"] == "Hotel prices are not available in USD for this search."
      and r["provider_error_code"] == "currency_unavailable",
      "every hotel in another currency: no hotels, and it says why")
r = map_cards({"data": {"hotels": []}})
check(r["provider_error"] is None and r["provider_error_code"] is None, "no hotels at all is not a currency error")

r = map_cards(SEARCH, currencies=["USD", "CHF"])
check([c["id"] for c in r["hotels"]] == ["h1", "h2", "h4"] and r["hotels"][1]["pricePerNight"] == [{"currency": "CHF", "price": 220.0}],
      "other currencies can be allowed explicitly")
r = map_cards(SEARCH, currencies='["usd"]')
check([c["id"] for c in r["hotels"]] == ["h1", "h4"], "currencies may arrive as a JSON string")
for rendered in ("['USD', 'EUR']", '["USD", "EUR"]', "USD, EUR", "USD EUR"):
    r = map_cards(SEARCH, currencies=rendered)
    check(r["currencies"] == ["USD", "EUR"], "currencies rendered as %r read as USD and EUR" % rendered)
EUR = {"data": {"hotels": [hotel(1, "EUR"), hotel(2, "USD"), hotel(3, "CHF")]}}
r = map_cards(EUR, currencies="['USD', 'EUR']")
eur = r["hotels"][0] if r["hotels"] else {}
check([c["id"] for c in r["hotels"]] == ["h1", "h2"] and r["excluded_by_currency"] == {"CHF": 1} and r["provider_error"] is None,
      "interim USD+EUR: EUR hotels are returned, others still left out")
check(eur.get("pricePerNight") == [{"currency": "EUR", "price": 220.0}] and eur.get("currency") == "EUR"
      and "price" not in eur and all(rm["pricePerNight"] == [{"currency": "EUR", "price": 220.0}] for rm in eur.get("rooms") or [None]),
      "an EUR hotel: pricePerNight [{EUR, price}] on the card and rooms, no display price")
r = map_cards(SEARCH, currencies=[])
check(r["currencies"] == ["USD"], "an empty list falls back to USD")
err = {"isError": True, "summary": "Hotels are temporarily unavailable.", "data": {"error": "x", "code": "request", "hotels": []}}
r = map_cards(err)
check(r["provider_error"] == "Hotels are temporarily unavailable." and r["provider_error_code"] == "request",
      "a provider error still wins over the currency message")

if failures:
    sys.exit("%d failure(s)" % len(failures))
