#!/usr/bin/env python3
"""playbooks/trip-intake.yaml: departure airport from the traveller's location
(adiona/frontend#55 Part 2), and misspelled places (#55 answer 2). Runs the intake
step's own code offline.

Darya's acceptance criteria, one check each (marked AC):
  * the optional user_location input is accepted without errors;
  * with a location, the departure question is a yes/no naming the nearest city and airport;
  * "no" leads to the open question;
  * without a location, the playbook behaves as it does today;
  * a departure city the user already gave is never asked for again.
Plus: a small nearby airport is not suggested when a bigger one is in reach.
"""
import sys
from datetime import date

import yaml

failures = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


doc = yaml.safe_load(open("playbooks/trip-intake.yaml"))
steps = {s["step"]: s for s in doc["workflow"]}
lib = {"_INTAKE_LIBRARY_ONLY": True}
exec(steps["intake_turn"]["tool"]["code"], lib)
run_turn, rule_read, suggestion = lib["run_turn"], lib["rule_read"], lib["departure_suggestion"]
TODAY = date(2026, 10, 16)
SAN_JOSE = {"city": "San Jose", "region": "CA", "country": "US", "lat": 37.3382, "lon": -121.8863}


def converse(turns, location=None, reader=rule_read):
    state, out = {}, []
    for text in turns:
        r = run_turn(state, text, {}, TODAY, reader, location)
        state = r["state"]
        out.append(r)
    return out


# ── The departure question ───────────────────────────────────────────────
r = converse(["A flight to Munich", "2026-11-03, one way"], SAN_JOSE)
first = converse(["A flight to Munich"], SAN_JOSE)[-1]
check(first["asked"] == ["origin_confirm"] and "Are you flying from San Jose (SJC)?" in first["bot_message"],
      "AC: with a location, the departure question is a yes/no naming the nearest city and airport: %s" % first["bot_message"])
r = converse(["A one-way flight to Munich on 2026-11-03"], SAN_JOSE)[-1]
check(r["asked"] == ["origin_confirm"] and "travelers" in r["missing"],
      "the yes/no is asked on its own, not paired with the travellers question")
r = converse(["A flight to Munich", "yes"], SAN_JOSE)[-1]
check(r["state"].get("origin_code") == "SJC" and "origin" not in r["missing"] and "origin_confirm" not in r["missing"],
      "yes: the suggested airport is the departure")
r = converse(["A flight to Munich", "Yep, that's right"], SAN_JOSE)[-1]
check(r["state"].get("origin_code") == "SJC", "yes in other words")
r = converse(["A flight to Munich", "no"], SAN_JOSE)[-1]
check(r["asked"] == ["origin"] and "Which city or airport are you flying from?" in r["bot_message"]
      and not r["state"].get("origin_code"), "AC: no leads to the open question")
r = converse(["A flight to Munich", "no", "Oakland"], SAN_JOSE)[-1]
check(r["state"].get("origin_code") == "OAK", "...which is then answered as usual")
r = converse(["A flight to Munich", "no", "2026-11-03"], SAN_JOSE)[-1]
check("origin_confirm" not in r["missing"], "once declined, the suggestion is not offered again")
r = converse(["A flight to Munich", "No, from Oakland"], SAN_JOSE)[-1]
check(r["state"].get("origin_code") == "OAK", "naming another place answers the question")
r = converse(["A flight to Munich", "Yes, from Oakland"], SAN_JOSE)[-1]
check(r["state"].get("origin_code") == "OAK", "a named place wins over a yes")
r = converse(["A flight to Munich", "Oakland"], SAN_JOSE)[-1]
check(r["state"].get("origin_code") == "OAK", "a bare place answers it too")
r = converse(["A flight to Munich", "hmm"], SAN_JOSE)[-1]
check(r["asked"] == ["origin_confirm"], "an unclear answer asks again")

# The model's yes/no.
def model(confirm):
    def read(text, state, awaiting, today):
        out = rule_read(text, state, awaiting, today)
        if "origin_confirm" in awaiting:
            out["confirm"] = confirm
        return out
    return read
r = converse(["A flight to Munich", "sounds good"], SAN_JOSE, reader=model(True))[-1]
check(r["state"].get("origin_code") == "SJC", "the model's confirm: true takes the suggestion")
r = converse(["A flight to Munich", "I'd rather not"], SAN_JOSE, reader=model(False))[-1]
check(r["asked"] == ["origin"], "the model's confirm: false asks the open question")

# AC: without a location, as today.
for loc, how in ((None, "none"), ({}, "empty"), ({"lat": "north", "city": ""}, "malformed"), ({"city": "Atlantis"}, "unknown city")):
    r = converse(["A flight to Munich"], loc)[-1]
    check(r["asked"] == ["origin"] and "Which city or airport are you flying from?" in r["bot_message"],
          "AC: without a usable location (%s), the open question as today" % how)
check(converse(["A flight to Munich"])[-1]["bot_message"] == converse(["A flight to Munich"], {})[-1]["bot_message"],
      "AC: no location is exactly today's behaviour")

# AC: a departure already given is never asked again.
r = converse(["A flight from Oakland to Munich"], SAN_JOSE)[-1]
check(r["state"].get("origin_code") == "OAK" and not any(a.startswith("origin") for a in r["asked"]),
      "AC: a departure the user already gave is never asked for again")
r = converse(["A flight to Munich", "yes", "2026-11-03, one way"], SAN_JOSE)[-1]
check(not any(a.startswith("origin") for a in r["missing"]), "...nor after accepting the suggestion")
r = converse(["A hotel in Munich"], SAN_JOSE)[-1]
check(not any(a.startswith("origin") for a in r["missing"]), "a hotel-only trip is not asked about a departure")

# The suggestion itself: the nearest airport, a bigger one when in reach.
check(suggestion({"user_location": SAN_JOSE}) == "SJC", "San Jose -> SJC")
check(suggestion({"user_location": {"lat": 38.2975, "lon": -122.2869}}) == "OAK",
      "Napa (no airport): the nearest large airport, Oakland")
check(suggestion({"user_location": {"lat": 38.5090, "lon": -122.8130}}) in ("SFO", "OAK", "SMF"),
      "next to Santa Rosa's small airport (STS): a bigger one nearby is suggested instead")
check(suggestion({"user_location": {"city": "San Jose", "region": "California"}}) == "SJC",
      "a city without coordinates is found by name")
check(suggestion({"user_location": {"lat": 0.0, "lon": -150.0}}) is None, "nothing within reach: no suggestion")
check(suggestion({"user_location": {"lat": 37.3382, "city": "San Jose", "region": "California"}}) == "SJC",
      "a latitude without a longitude is not a position: the city is used")
check(suggestion({"user_location": SAN_JOSE, "origin_suggestion_declined": True}) is None, "declined: no suggestion")
wl = doc["workload"]
check(wl.get("user_location") == {} and "user_location" in steps["intake_turn"]["tool"]["input"],
      "AC: user_location is an optional input")

# ── Misspelled places (#55 answer 2) ─────────────────────────────────────
def typo_model(text_to_facts):
    def read(text, state, awaiting, today):
        out = rule_read(text, state, awaiting, today)
        for typed, facts in text_to_facts.items():
            if typed.lower() in text.lower():
                out["destination"] = dict({"text": typed, "kind": "city"}, **facts)
        return out
    return read
r = converse(["A flight from SFO to Amsterdm"], reader=typo_model({"Amsterdm": {"corrected": "Amsterdam"}}))[-1]
check(r["state"]["destination"]["text"] == "Amsterdam" and r["state"].get("destination_code") == "AMS"
      and "couldn't find" not in r["bot_message"], "a typo the model recognises is corrected without asking")
check(r["state"]["destination"].get("typed_as") == "Amsterdm", "...and what was typed is kept")
r = converse(["A hotel in Amsterdm", "Nov 3 to Nov 6", "2 adults, no kids", "1 room"],
             reader=typo_model({"Amsterdm": {"corrected": "Amsterdam"}}))[-1]
check(r["forms"] and r["forms"][0]["payload"]["criteria"]["destination"] == "Amsterdam",
      "hotel-only too: the hotel form gets the corrected city")
r = converse(["A flight from SFO to Xqzzy"], reader=typo_model({"Xqzzy": {"exists": False}}))[-1]
check("We couldn't find a place called \"Xqzzy\". Please check the spelling or enter a nearby city." in r["bot_message"]
      and not r["state"].get("destination") and r["asked"][:1] == ["destination"],
      "a place that does not exist: asked to check the spelling, and asked again")
r = converse(["A flight from SFO to Pariz"], reader=typo_model({"Pariz": {"corrected": "Albuquerque"}}))[-1]
check("couldn't find a place called \"Pariz\"" in r["bot_message"] and not r["state"].get("destination"),
      "a 'correction' under 60% alike to the text is not used")

def airport_model(text, state, awaiting, today):
    out = rule_read(text, state, awaiting, today)
    out["destination"] = {"text": "LHR", "kind": "airport", "corrected": "London"}
    return out
r = converse(["A flight from SFO to LHR"], reader=airport_model)[-1]
check(r["state"]["destination"]["text"] == "LHR" and r["state"].get("destination_code") == "LHR",
      "an airport code is never 'corrected' into a city")

if failures:
    sys.exit("%d failure(s)" % len(failures))
