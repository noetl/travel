#!/usr/bin/env python3
"""playbooks/trip-intake.yaml: airport lookup for cities, islands and regions
(adiona/frontend#55 Part 1). Runs the intake step's own embedded `code:` with no
network.

  * Darya's eight test inputs, exactly as the issue lists them: Kauai, Maui, Big
    Island, Hawaii, Santorini, Napa, Portland, Munich. Each gives an airport or a
    clarifying question, never nothing.
  * The model is scripted (MODEL below: what it is asked to say about a place);
    the rule reader, used when the model is down, is checked where the airport
    table alone can answer (Kauai, Santorini, Portland, Munich).
  * An island with a hotel search asks "Which city or area on {island} would you
    like to stay in?"; a flight-only trip doesn't.
  * Codes the model proposes are kept only if they are in the airport table.
  * user_location (Part 2) is accepted and changes nothing yet.
"""
import json
import sys
from datetime import date

import yaml

PLAYBOOK = "playbooks/trip-intake.yaml"
TODAY = date(2026, 10, 16)
failures = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


doc = yaml.safe_load(open(PLAYBOOK))
steps = {s["step"]: s for s in doc["workflow"]}
lib = {"_INTAKE_LIBRARY_ONLY": True}
exec(steps["intake_turn"]["tool"]["code"], lib)
run_turn, rule_read, BY_CODE = lib["run_turn"], lib["rule_read"], lib["BY_CODE"]

check(len(lib["ALL_AIRPORTS"]) > 3000, "the full airport table parsed (%d airports)" % len(lib["ALL_AIRPORTS"]))
for code in ("LIH", "OGG", "KOA", "ITO", "OAK", "PWM", "PDX", "JTR", "MUC", "SFO"):
    check(code in BY_CODE, "%s is in the airport table" % code)

# What the model says about each place (the prompt asks for kind, coordinates,
# main commercial airports, a region's islands and a name's namesakes).
PLACES = {
    "Kauai": {"kind": "island", "lat": 22.07, "lon": -159.5, "airports": ["LIH"]},
    "Maui": {"kind": "island", "lat": 20.8, "lon": -156.33, "airports": ["OGG"]},
    "Big Island": {"kind": "island", "lat": 19.6, "lon": -155.5, "airports": ["KOA", "ITO"]},
    "Hawaii": {"kind": "region", "lat": 20.8, "lon": -156.3, "islands": [
        {"name": "Oahu", "airports": ["HNL"]}, {"name": "Maui", "airports": ["OGG"]},
        {"name": "Kauai", "airports": ["LIH"]}, {"name": "Big Island", "airports": ["KOA", "ITO"]}]},
    "Santorini": {"kind": "island", "lat": 36.39, "lon": 25.46, "airports": ["JTR"]},
    "Napa": {"kind": "city", "lat": 38.2975, "lon": -122.2869, "airports": []},
    "Portland": {"kind": "city", "lat": 45.52, "lon": -122.68, "airports": ["PDX"]},
    "Munich": {"kind": "city", "lat": 48.14, "lon": 11.58, "airports": ["MUC"]},
}


def model(text, state, awaiting, today):
    """A scripted model: reads the intent, the destination (with its facts), SFO as
    the origin, a bare place answer, and the rest through the rule reader."""
    out = rule_read(text, state, awaiting, today)
    out.pop("destination", None)
    for name, facts in PLACES.items():
        if name.lower() in text.lower() and "from" not in text.lower():
            out["destination"] = dict({"text": name}, **facts)
            break
    if "hotel_area" in awaiting and "destination" in out and out["destination"]["kind"] == "city":
        out["hotel_area"] = {"text": out.pop("destination")["text"]}
    if "hotel_area" in awaiting and "destination" not in out and "origin" not in out and text.istitle():
        out["hotel_area"] = {"text": text}
    return out


def converse(turns, reader=model, location=None):
    state, out = {}, []
    for text in turns:
        r = run_turn(state, text, {}, TODAY, reader, location)
        state = r["state"]
        out.append(r)
    return out


def last(turns, reader=model):
    return converse(turns, reader)[-1]


def asks(r, item):
    return item in r["asked"]


# ── Darya's eight inputs ─────────────────────────────────────────────────

# Kauai: LIH, plus the hotel city/area question if hotels were requested.
for reader, how in ((model, "model"), (rule_read, "rule reader")):
    r = last(["Flights and a hotel in Kauai"], reader)
    check(r["state"].get("destination_code") == "LIH", "Kauai -> LIH (%s)" % how)
    check(r["asked"] == ["hotel_area"] and "Which city or area on Kauai would you like to stay in?" in r["bot_message"],
          "Kauai with a hotel asks which city or area on Kauai (%s)" % how)
    r = last(["A flight to Kauai"], reader)
    check(r["state"].get("destination_code") == "LIH" and "hotel_area" not in r["missing"],
          "Kauai, flight only: LIH and no hotel-area question (%s)" % how)
    r = last(["A hotel in Kauai"], reader)
    check(r["asked"] == ["hotel_area"], "Kauai, hotel only: the hotel-area question (%s)" % how)

# Maui: OGG, plus the hotel city/area question.
r = last(["Flights and a hotel in Maui"])
check(r["state"].get("destination_code") == "OGG", "Maui -> OGG")
check(r["asked"] == ["hotel_area"] and "Which city or area on Maui would you like to stay in?" in r["bot_message"],
      "Maui with a hotel asks which city or area on Maui")

# Big Island: KOA and ITO, ask the user to choose.
r = last(["A flight to the Big Island"])
check(r["state"].get("destination_options") == ["KOA", "ITO"] and r["asked"] == ["airport:destination"],
      "Big Island -> KOA and ITO, asked to choose")
check("KOA" in r["bot_message"] and "ITO" in r["bot_message"] and "Which one" in r["bot_message"],
      "Big Island: the question lists both airports: %s" % r["bot_message"])
r = last(["A flight to the Big Island", "Hilo"])
check(r["state"].get("destination_code") == "ITO", "Big Island: answering 'Hilo' picks ITO")

# Hawaii: ask which island.
r = last(["Flights and a hotel in Hawaii"])
check(r["asked"] == ["island:destination"] and "Which island" in r["bot_message"]
      and all(i in r["bot_message"] for i in ("Oahu", "Maui", "Kauai", "Big Island")),
      "Hawaii asks which island: %s" % r["bot_message"])
check(not r["state"].get("destination_code") and not r["forms"], "Hawaii alone picks no airport")
r = last(["Flights and a hotel in Hawaii", "Maui"])
check(r["state"]["destination"]["text"] == "Maui" and r["state"].get("destination_code") == "OGG",
      "Hawaii, then 'Maui' -> OGG")
check(r["asked"] == ["hotel_area"], "Hawaii, then Maui, then the hotel-area question")
r = last(["A hotel in Hawaii"])
check(r["asked"] == ["island:destination"], "Hawaii, hotel only, still asks which island")

# Santorini: JTR.
for reader, how in ((model, "model"), (rule_read, "rule reader")):
    r = last(["A flight to Santorini"], reader)
    check(r["state"].get("destination_code") == "JTR", "Santorini -> JTR (%s)" % how)

# Napa (no airport): the nearest airports, for example SFO and OAK.
r = last(["A flight to Napa"])
opts = r["state"].get("destination_options") or []
check({"SFO", "OAK"} <= set(opts) and len(opts) <= 3, "Napa -> the nearest airports, SFO and OAK among them: %s" % opts)
check(r["asked"] == ["airport:destination"] and "no airport of its own" in r["bot_message"],
      "Napa: says it has no airport and asks which nearby one: %s" % r["bot_message"])
r = last(["A flight to Napa", "OAK"])
check(r["state"].get("destination_code") == "OAK", "Napa: answering 'OAK' picks it")
r = last(["A hotel in Napa"])
check("hotel_area" not in r["missing"] and not any(m.startswith("airport") for m in r["missing"]),
      "Napa, hotel only: no airport and no area question (it is a town)")

# Portland: ask Oregon (PDX) or Maine (PWM).
for reader, how in ((model, "model"), (rule_read, "rule reader")):
    r = last(["A flight to Portland"], reader)
    labels = [m["label"] for m in r["state"].get("destination_matches") or []]
    check(r["asked"] == ["which:destination"] and labels == ["Portland, Oregon", "Portland, Maine"],
          "Portland asks which one (%s): %s" % (how, labels))
    check("Portland, Oregon (PDX)" in r["bot_message"] and "Portland, Maine (PWM)" in r["bot_message"],
          "Portland: the question names Oregon (PDX) and Maine (PWM) (%s)" % how)
    r = last(["A flight to Portland", "Maine"], reader)
    check(r["state"].get("destination_code") == "PWM", "Portland, then 'Maine' -> PWM (%s)" % how)
    r = last(["A flight to Portland", "the first one"], reader)
    check(r["state"].get("destination_code") == "PDX", "Portland, then 'the first one' -> PDX (%s)" % how)
r = last(["A flight to Portland, Maine"], rule_read)
check(r["state"].get("destination_code") == "PWM" and "which:destination" not in r["missing"],
      "'Portland, Maine' needs no question")
r = last(["A hotel in Portland"])
check(r["asked"] == ["which:destination"] and "(PDX)" not in r["bot_message"],
      "Portland, hotel only: asks which one, without airport codes")
r = last(["A hotel in Portland", "Oregon", "Nov 3 to Nov 6", "2 adults, no kids", "1 room"])
check(r["forms"] and r["forms"][0]["payload"]["criteria"]["destination"] == "Portland, Oregon",
      "Portland, then Oregon: the hotel form searches Portland, Oregon")

# Munich: MUC.
for reader, how in ((model, "model"), (rule_read, "rule reader")):
    r = last(["A flight to Munich"], reader)
    check(r["state"].get("destination_code") == "MUC", "Munich -> MUC (%s)" % how)

# Every input gives an airport or a question, never nothing.
for name in PLACES:
    r = last(["Flights and a hotel in %s" % name])
    check(r["state"].get("destination_code") or r["asked"], "%s: an airport or a question" % name)

# ── A whole island trip ──────────────────────────────────────────────────
r = last(["Flights and a hotel in Kauai", "Poipu", "from SFO", "Nov 3 to Nov 8", "2 adults, no kids", "1 room"])
hotel, flight = (r["forms"] + [{}, {}])[:2]
check(hotel.get("payload", {}).get("criteria", {}).get("destination") == "Poipu, Kauai",
      "Kauai, then Poipu: the hotel form searches Poipu, Kauai")
check(flight.get("payload", {}).get("criteria", {}).get("destination") == "LIH"
      and flight["payload"]["criteria"]["origin"] == "SFO", "Kauai: the flight form goes SFO -> LIH")

# ── The model's codes are checked against the table ──────────────────────
PLACES["Atlantis"] = {"kind": "island", "lat": 36.0, "lon": -30.0, "airports": ["ZZQ"]}
r = last(["A flight to Atlantis"])
check(not r["state"].get("destination_code") and r["asked"] == ["airport_unknown:destination"],
      "a code outside the table is never used: asks which airport instead")
del PLACES["Atlantis"]

# London stays as it was: its three major airports, no namesakes.
r = last(["A flight to London"], rule_read)
check(r["state"].get("destination_options") == ["LHR", "LGW", "STN"], "London still offers LHR, LGW and STN")

# ── user_location (Part 2): accepted, kept, changes nothing ──────────────
loc = {"city": "San Jose", "region": "CA", "country": "US", "lat": 37.3382, "lon": -121.8863}
turns = ["Flights and a hotel in Munich", "Nov 3 to Nov 8"]
with_loc, without = converse(turns, location=loc), converse(turns)
check(with_loc[-1]["state"].get("user_location") == loc, "user_location is accepted and kept in the intake state")
check([r["bot_message"] for r in with_loc] == [r["bot_message"] for r in without]
      and [r["asked"] for r in with_loc] == [r["asked"] for r in without]
      and with_loc[-1]["forms"] == without[-1]["forms"],
      "user_location changes no question and no form")
check(converse(["hi"], location={"lat": "north", "city": ""})[-1]["state"].get("user_location") is None,
      "a malformed user_location is dropped")
wl = doc["workload"]
check(wl.get("user_location") == {} and "user_location" in steps["intake_turn"]["tool"]["input"],
      "user_location is an optional workload input passed to the intake step")

if failures:
    sys.exit("%d failure(s)" % len(failures))
