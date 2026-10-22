#!/usr/bin/env python3
"""playbooks/trip-intake.yaml (adiona/frontend#55): runs the intake step's own embedded
`code:` with no network.

  * Darya's four examples from #55 come out EXACTLY: same keys, same nesting, same order.
  * It keeps asking until the form is complete: one or two questions a turn, never one
    already answered; corrections, validation, airports, coordinates, combined trips.
  * Nothing is invented: optional fields only when given, `children` is [] when none.
  * It cannot search: the playbook calls no provider but mcp/firestore.
  * Thread access is the planner's, byte for byte.
"""
import json
import re
import sys
from datetime import date

import yaml

PLAYBOOK = "playbooks/trip-intake.yaml"
PLANNER = "playbooks/itinerary-planner.yaml"
TODAY = date(2026, 10, 16)

failures = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


doc = yaml.safe_load(open(PLAYBOOK))
steps = {s["step"]: s for s in doc["workflow"]}
code = steps["intake_turn"]["tool"]["code"]

lib = {"_INTAKE_LIBRARY_ONLY": True}
exec(code, lib)
run_turn, rule_read = lib["run_turn"], lib["rule_read"]
check(len(lib["AIRPORTS"]) >= 150, "the airport table parsed (%d airports)" % len(lib["AIRPORTS"]))


def converse(turns, reader=rule_read):
    """Run the turns; return every turn's result."""
    state, out = {}, []
    for turn in turns:
        text, payload = (turn, {}) if isinstance(turn, str) else turn
        r = run_turn(state, text, payload, TODAY, reader)
        state = r["state"]
        out.append(r)
    return out


def form(r, i=0):
    return r["forms"][i] if len(r["forms"]) > i else {"payload": {"criteria": {}}}


def same(a, b):
    """Equal values AND the same key order at every level."""
    return json.dumps(a) == json.dumps(b)


# ── Darya's four examples, exactly ───────────────────────────────────────

EXAMPLES = [
    ("hotel, 2 adults + 1 child, coordinates",
     [("Hotel in Paris from Nov 1 to Nov 5 within 20 km, 2 adults and 1 child aged 8, 1 room",
       {"latitude": 48.8566, "longitude": 2.3522})],
     {"widget_type": "hotel_search_form", "payload": {"criteria": {
         "destination": "Paris", "latitude": 48.8566, "longitude": 2.3522, "radius": 20,
         "checkIn": "2026-11-01", "checkOut": "2026-11-05", "rooms": 1, "adults": 2,
         "children": [{"age": 8}]}, "defaultDestination": "Paris"}}),
    ("hotel by name, no coordinates",
     ["A room at Hotel Bel-Air, check-in Dec 10, check-out Dec 14, 2 adults, no kids"],
     {"widget_type": "hotel_search_form", "payload": {"criteria": {
         "destination": "Hotel Bel-Air", "checkIn": "2026-12-10", "checkOut": "2026-12-14",
         "rooms": 1, "adults": 2, "children": []}}}),
    ("round trip, 2 adults + 2 children",
     ["Round trip flights from SFO to JFK, Nov 1 to Nov 8, 2 adults and 2 kids aged 8 and 4"],
     {"widget_type": "flight_search_form", "payload": {"criteria": {
         "tripType": "round_trip", "origin": "SFO", "destination": "JFK", "departDate": "2026-11-01",
         "returnDate": "2026-11-08", "travelers": {"adults": 2, "children": [{"age": 8}, {"age": 4}]}},
         "defaultDestination": "JFK"}}),
    ("one way, 1 adult, no returnDate",
     ["One way flight from LAX to London on Dec 15 for 1 adult, no kids", "LHR"],
     {"widget_type": "flight_search_form", "payload": {"criteria": {
         "tripType": "one_way", "origin": "LAX", "destination": "LHR", "departDate": "2026-12-15",
         "travelers": {"adults": 1, "children": []}}}}),
]
for label, turns, expected in EXAMPLES:
    last = converse(turns)[-1]
    check(len(last["forms"]) == 1 and same(form(last), expected),
          "#55 example exact: %s" % label + ("" if last["forms"] and same(form(last), expected)
                                             else " -> %s" % json.dumps(last["forms"])))


# The same examples through the model path: the model's JSON goes through the
# same cleaning and rules, so the output is identical.
def scripted(*patches):
    queue = list(patches)
    return lambda text, state, awaiting, today: queue.pop(0)


llm_ex1 = converse([("Paris, Nov 1-5, 20km radius, me + wife + our 8 year old, one room",
                     {"latitude": 48.8566, "longitude": 2.3522})],
                   scripted({"intent": "hotel", "destination": {"text": "Paris", "kind": "city"},
                             "start_date": "2026-11-01", "end_date": "2026-11-05", "radius": 20,
                             "adults": 2, "children_ages": [8], "rooms": 1}))[-1]
check(same(form(llm_ex1), EXAMPLES[0][2]), "model path: example 1 exact")
llm_ex4 = converse(["one way LA to London Dec 15 just me", "Heathrow please"],
                   scripted({"intent": "flight", "trip_type": "one_way", "origin": {"text": "LAX", "kind": "airport"},
                             "destination": {"text": "London", "kind": "city"}, "depart_date": "2026-12-15",
                             "adults": 1, "children_count": 0},
                            {"airport_code": "LHR"}))[-1]
check(same(form(llm_ex4), EXAMPLES[3][2]), "model path: example 4 exact (an offered airport, no defaultDestination)")
junk = converse(["x"], scripted({"intent": "cruise", "adults": "many", "rooms": True, "children_ages": ["eight"],
                                 "check_in": "soon", "destination": {"text": ""}, "made_up": 1}))[-1]
check(junk["state"].get("adults") is None and not junk["patch"], "model output outside the schema is dropped")

# ── Keeps asking, 1-2 questions a turn, never re-asks ────────────────────

hotel = converse(["I need a hotel", "Rome", "Nov 3 to Nov 7", "2", "1"])
asked = [r["asked"] for r in hotel]
check(asked[0] == ["destination"] and asked[1] == ["dates"],
      "destination first, then the dates on their own, got %s" % asked[:2])
check(all(1 <= len(a) <= 2 for a in asked[:-1]) and asked[-1] == [], "one or two questions per turn until complete")
def answered_then_asked(results):
    """Questions asked for a field that an EARLIER turn had already filled."""
    bad, filled = [], set()
    for r in results:
        bad += [q for q in r["asked"] if q in filled]
        filled |= {q for q in ("intent", "destination", "origin", "dates", "trip_type", "return_date",
                               "adults", "children_ages", "rooms") if q not in r["missing"]}
    return bad


check(not answered_then_asked(hotel), "a field once answered is never asked again")
check(hotel[-1]["forms"] and form(hotel[-1])["payload"]["criteria"]["destination"] == "Rome",
      "the hotel form comes back once everything is known")
check(all(not r["forms"] for r in hotel[:-1]), "no form before every required field is known")
check(hotel[0]["bot_message"] == "Where would you like to stay?"
      and hotel[1]["bot_message"] == "What are your check-in and check-out dates?",
      "the questions read naturally: %r" % hotel[0]["bot_message"])

first = converse(["hello"])[0]
check(first["asked"] == ["intent"] and "flights, a hotel, or both" in first["bot_message"],
      "with no intent it asks flights / hotel / both first")

kids = converse(["Flight from SFO to Lisbon Nov 10 one way, 2 adults and 2 children", "7 and 10"])
check(kids[0]["asked"] == ["children_ages"], "children without ages: asks the ages")
check(form(kids[1])["payload"]["criteria"]["travelers"]["children"] == [{"age": 7}, {"age": 10}],
      "the ages answer completes the travellers")
check(form(kids[1])["payload"]["criteria"]["destination"] == "LIS", "a one-airport city resolves to its code")

trip = converse(["Flights from SFO to Lisbon on Nov 10 for 2 adults, no kids", "round trip", "Nov 20"])
check(trip[0]["asked"] == ["trip_type"], "a departure with no return: asks one-way or round trip")
check(trip[1]["asked"] == ["return_date"], "round trip: then asks the return date")
check(form(trip[2])["payload"]["criteria"]["returnDate"] == "2026-11-20", "the return date completes it")

# ── Validation ───────────────────────────────────────────────────────────

past = converse(["Hotel in Rome, check-in 2026-10-01, check-out 2026-10-05, 2 adults, 1 room"])[0]
check("in the past" in past["bot_message"] and "dates" in past["asked"] and not past["forms"],
      "a past date is refused and asked again")
backwards = converse(["Round trip flight SFO to Lisbon departing Nov 10 returning Nov 2, 1 adult"])[0]
check("return date can't be before" in backwards["bot_message"] and not backwards["forms"],
      "a return before the departure is refused")
same_day = converse(["Round trip flight from SFO to Lisbon Nov 10 to Nov 10, 1 adult, no kids"])[0]
check(same_day["forms"] and form(same_day)["payload"]["criteria"]["returnDate"] == "2026-11-10",
      "a same-day return is allowed (return >= departure)")
zero_nights = converse(["Hotel in Rome, check-in Nov 10, check-out Nov 10, 2 adults, 1 room"])[0]
check("Check-out has to be after check-in" in zero_nights["bot_message"] and not zero_nights["forms"],
      "check-out on the check-in day is refused")
rooms = converse(["Hotel in Rome Nov 3 to Nov 7, 1 adult, 3 rooms"])[0]
check("at least one adult" in rooms["bot_message"] and "rooms" in rooms["asked"], "more rooms than adults is refused")
many = converse(["Flight SFO to Lisbon Nov 10 one way, 12 adults"])[0]
check("1 to 9 adults" in many["bot_message"] and "travelers" in many["asked"], "over the flight form's 9 adults is refused")

# ── Corrections ──────────────────────────────────────────────────────────

fix = converse(["Hotel in Paris Nov 1 to Nov 5, 2 adults, no kids, 1 room", "Actually make it Rome", "3 adults"])
check(form(fix[1])["payload"]["criteria"]["destination"] == "Rome", "a changed destination updates the form")
check(form(fix[2])["payload"]["criteria"]["adults"] == 3, "a changed count updates the form")
check(fix[1]["asked"] == [] and fix[2]["asked"] == [], "a correction asks nothing new")
oneway = converse(["Round trip flights from SFO to JFK Nov 1 to Nov 8, 2 adults, no kids", "make it one way"])
check("returnDate" not in form(oneway[1])["payload"]["criteria"]
      and form(oneway[1])["payload"]["criteria"]["tripType"] == "one_way",
      "switching to one way drops returnDate")
switch = converse(["Flight and hotel to Rome from SFO Nov 3 to Nov 7, 2 adults, no kids", "just the hotel", "1 room"])
check([f["widget_type"] for f in switch[2]["forms"]] == ["hotel_search_form"], "switching to hotel-only drops the flight")

# ── Airports ─────────────────────────────────────────────────────────────

paris = converse(["Flight from SFO to Paris on Nov 10, one way, 1 adult"])[0]
check(paris["asked"] == ["airport:destination"] and "CDG" in paris["bot_message"] and "ORY" in paris["bot_message"],
      "a multi-airport city is a question with its airports, asked on its own")
picked = converse(["Flight from SFO to Paris on Nov 10, one way, 1 adult, no kids", "CDG"])[-1]
check(picked["forms"] and "defaultDestination" not in form(picked)["payload"],
      "a picked airport sets no defaultDestination")
nowhere = converse(["Flight from SFO to Springfield on Nov 10, one way, 1 adult"])[0]
check(not nowhere["forms"] and ("destination" in nowhere["asked"]
                               or any(a.startswith(("airport", "which:")) for a in nowhere["asked"])),
      "a place with no known airport is asked about, not guessed")
allowed = set(lib["BY_CODE"])
check(all(f["payload"]["criteria"][k] in allowed for r in [picked, kids[1], trip[2]] for f in r["forms"]
          for k in ("origin", "destination")), "every returned airport code is one the form can prefill")

# ── Coordinates and named hotels ─────────────────────────────────────────

pin = converse([("Hotel Nov 1 to Nov 5, 2 adults, no kids, 1 room", {"latitude": 48.86, "longitude": 2.35})])[0]
crit = form(pin)["payload"]["criteria"] if pin["forms"] else {}
check(crit.get("destination") == "Paris" and crit.get("latitude") == 48.86 and "radius" not in crit,
      "coordinates only: destination is the city name, coordinates kept, no radius invented")
check(pin["forms"] and "defaultDestination" not in form(pin)["payload"],
      "coordinates only: no defaultDestination (the user didn't name it)")
sea = converse([("Hotel Nov 1 to Nov 5, 2 adults, no kids, 1 room", {"latitude": 0.0, "longitude": -30.0})])[0]
check(not sea["forms"] and "destination" in sea["asked"], "coordinates far from any known city: asks for the city")
named = converse([("A room at Hotel Bel-Air Dec 10 to Dec 14, 2 adults, no kids", {"latitude": 34.08, "longitude": -118.44})])[0]
check(named["forms"] and "latitude" not in form(named)["payload"]["criteria"],
      "a named hotel drops the coordinates")

# ── Combined trip ────────────────────────────────────────────────────────

combo = converse(["I need a flight and a hotel in Rome", "From SFO", "Nov 3 to Nov 7", "2 adults and 1 room"])
check([f["widget_type"] for f in combo[-1]["forms"]] == ["hotel_search_form", "flight_search_form"],
      "a combined trip returns both forms, hotel first")
asked_items = [q for r in combo for q in r["asked"]]
check(not answered_then_asked(combo) and "destination" not in asked_items and "return_date" not in asked_items,
      "shared details are never asked again once given; one dates question covers both forms")
h, f = combo[-1]["forms"]
check(h["payload"]["criteria"]["checkIn"] == f["payload"]["criteria"]["departDate"] == "2026-11-03"
      and h["payload"]["criteria"]["checkOut"] == f["payload"]["criteria"]["returnDate"] == "2026-11-07",
      "the trip dates fill both forms")
check(all(not r["forms"] for r in combo[:-1]), "neither form returns until both are complete")

# ── Nothing invented ─────────────────────────────────────────────────────

HOTEL_KEYS = ["destination", "latitude", "longitude", "radius", "checkIn", "checkOut", "rooms", "adults", "children"]
FLIGHT_KEYS = ["tripType", "origin", "destination", "departDate", "returnDate", "travelers"]
all_forms = [f for r in hotel + kids + trip + fix + oneway + switch + combo + [picked, pin, named] for f in r["forms"]]
check(all(list(f["payload"]["criteria"]) == [k for k in (HOTEL_KEYS if f["widget_type"] == "hotel_search_form"
                                                          else FLIGHT_KEYS) if k in f["payload"]["criteria"]]
          for f in all_forms), "every form uses only the form's field names, in the form's order")
plain = converse(["Hotel in Rome Nov 3 to Nov 7, 2 adults, no kids, 1 room"])[0]["forms"][0]
check(same(plain["payload"]["criteria"], {"destination": "Rome", "checkIn": "2026-11-03", "checkOut": "2026-11-07",
                                          "rooms": 1, "adults": 2, "children": []}),
      "no children mentioned: children [] and no optional field appears")

# ── The playbook cannot search ───────────────────────────────────────────

paths = [s["tool"].get("path") for s in doc["workflow"] if s["tool"].get("kind") == "playbook"]
check(paths == ["automation/agents/mcp/firestore"], "the only child playbook is mcp/firestore: %s" % paths)
src = open(PLAYBOOK).read().lower()
check(not re.search(r"duffel|hotelbeds|google-places|places\.googleapis|amadeus", src), "no flight, hotel or places provider is named")
check(sorted(doc["metadata"]["capabilities"]) == ["ai:anthropic", "ai:vertex-ai", "mcp:firestore"],
      "capabilities: firestore + the model only (Claude, Gemini as the rollback)")
# www.googleapis.com/auth/cloud-platform is an OAuth scope NAME, not a host contacted.
hosts = set(re.findall(r"https?://([a-z0-9.-]+)", code.replace("https://www.googleapis.com/auth/cloud-platform", "")))
# Firestore is read directly for one thing only: cached place facts (intake_place_facts);
# everything the turn saves still goes through mcp/firestore in persist_turn.
# Claude (api.anthropic.com) with its key from Secret Manager; Vertex AI kept as the rollback.
check(hosts == {"metadata.google.internal", "firestore.googleapis.com", "api.anthropic.com", "secretmanager.googleapis.com"}
      and '"aiplatform.googleapis.com"' in code,
      "the intake step reaches only the metadata server, the model (Claude or Vertex), its key and Firestore: %s" % sorted(hosts))
fs_urls = re.findall(r'"https://firestore\.googleapis\.com[^"]*"', code)
check(len(fs_urls) == 1 and "PLACE_CACHE_COLLECTION" in code[code.index(fs_urls[0]):code.index(fs_urls[0]) + 300]
      and "method=\"POST\"" not in code[code.index(fs_urls[0]):code.index(fs_urls[0]) + 300],
      "...and Firestore only to read intake_place_facts (a GET)")

# ── Thread access is the planner's, byte for byte ────────────────────────

planner = {s["step"]: s for s in yaml.safe_load(open(PLANNER))["workflow"]}
check(steps["load_state"]["tool"]["code"] == planner["load_slot_state"]["tool"]["code"],
      "load_state code == itinerary-planner load_slot_state")
check(steps["refuse_thread"]["tool"]["code"] == planner["refuse_thread"]["tool"]["code"],
      "refuse_thread code == itinerary-planner refuse_thread")
pin_in = dict(planner["load_slot_state"]["tool"]["input"], doc_path=None)
check(dict(steps["load_state"]["tool"]["input"], doc_path=None) == pin_in
      and steps["load_state"]["tool"]["input"]["doc_path"].endswith("/slot_state/intake"),
      "load_state bindings match; only the slot document differs")

# ── Darya's answers (adiona/frontend#55, 2026-10-16) ─────────────────────

# 1. Travellers are asked together: adults, whether children come, their ages.
TRAVELERS_Q = ("How many adults are traveling? Will any children be traveling as well? "
               "If so, please share each child's age.")
t1 = converse(["Hotel in Rome Nov 3 to Nov 7, 1 room"])[0]
check(t1["asked"] == ["travelers"] and TRAVELERS_Q in t1["bot_message"],
      "travellers are one question: adults, children and their ages (%r)" % t1["bot_message"])
t2 = converse(["Hotel in Rome Nov 3 to Nov 7, 1 room, 2 adults"])[0]
check(t2["asked"] == ["travelers"] and t2["bot_message"].startswith("Will any children be traveling as well?"),
      "adults already known: only the children part is asked")
t3 = converse(["Hotel in Rome Nov 3 to Nov 7, 1 room", "2 adults"])[-1]
check(form(t3)["payload"]["criteria"].get("children") == [],
      "asked about children together with adults, an answer naming no children means none: children []")
t4 = converse(["Hotel in Rome Nov 3 to Nov 7, 1 room", "2 adults and 2 kids 7 and 10"])[-1]
check(form(t4)["payload"]["criteria"].get("children") == [{"age": 7}, {"age": 10}],
      "the children's ages fill the form when given")
t5 = converse(["Hotel in Rome Nov 3 to Nov 7, 1 room", "2 adults and 2 children"])[-1]
check(t5["asked"] == ["children_ages"] and not t5["forms"], "children without ages: their ages are asked")

# 5. "Both" must return both forms. Darya's prod run (2026-10-16 21:13-21:19Z) replayed
#    with what the model actually proposed: "I am flying from San Francisco" came back as
#    intent `flight`, which used to drop the hotel.
both_run = converse([
    "I want to travel to Europe", "Both", "London", "Heathrow Airport (LHR)",
    "I am flying from San Francisco. Not sure about dates, sometime in November",
    "November 5 to November 15, 2 adults, no kids", "one room"],
    scripted({}, {"intent": "both"}, {"destination": {"text": "London", "kind": "city"}}, {"airport_code": "LHR"},
             {"intent": "flight", "origin": {"text": "San Francisco", "kind": "city"}},
             {"start_date": "2026-11-05", "end_date": "2026-11-15", "adults": 2, "children_count": 0},
             {"rooms": 1}))
check([f["widget_type"] for f in both_run[-1]["forms"]] == ["hotel_search_form", "flight_search_form"],
      "'both' returns BOTH forms even when a later message mentions flying: %s"
      % [f["widget_type"] for f in both_run[-1]["forms"]])
check(all(r["state"].get("intent") == "both" for r in both_run[1:]), "the intent stays `both` on every later turn")
add_hotel = converse(["Round trip flight from SFO to JFK Nov 5 to Nov 15, 2 adults, no kids", "what about hotel info", "one room"],
                     scripted({"intent": "flight", "origin": {"text": "SFO", "kind": "airport"},
                               "destination": {"text": "JFK", "kind": "airport"}, "start_date": "2026-11-05",
                               "end_date": "2026-11-15", "adults": 2, "children_count": 0, "trip_type": "round_trip"},
                              {"intent": "hotel"}, {"rooms": 1}))
check([f["widget_type"] for f in add_hotel[-1]["forms"]] == ["hotel_search_form", "flight_search_form"]
      and form(add_hotel[-1])["payload"]["criteria"]["checkIn"] == "2026-11-05",
      "asking about a hotel after a flight adds it (both forms; the hotel reuses the flight's dates)")
narrow = converse(["Flight and hotel to Rome from SFO Nov 3 to Nov 7, 2 adults, no kids", "actually just the flight"])
check([f["widget_type"] for f in narrow[-1]["forms"]] == ["flight_search_form"], "an explicit 'just the flight' still narrows")
check(lib["resolve_intent"]("both", "flight", "I am flying from SFO") == "both"
      and lib["resolve_intent"]("flight", "hotel", "what about a hotel") == "both"
      and lib["resolve_intent"]("both", "hotel", "no flight needed") == "hotel"
      and lib["resolve_intent"](None, "flight", "a flight") == "flight", "intent resolution rules")

# ── The date picker: the planner's date_range_picker, rendered by the chat ──

schema = json.load(open("playbooks/widget-contract/date_range_picker.schema.json"))
planner_steps = {s["step"]: s for s in yaml.safe_load(open(PLANNER))["workflow"]}
planner_render = planner_steps["render_widget_chat"]["tool"]["code"]
d1 = converse(["I need a hotel in Rome"])[0]
w = d1["widget"] or {}
check(w.get("widget_type") == "date_range_picker" and w.get("schema_version") == 1 and w.get("variant") == "compact"
      and '_env("date_range_picker", "compact"' in planner_render,
      "asking the dates returns the planner's date_range_picker envelope (schema_version 1, variant compact)")
pay = w.get("payload") or {}
check(set(schema["required"]) <= set(pay) and set(pay) <= set(schema["properties"]),
      "the picker payload satisfies the widget contract schema: %s" % sorted(pay))
check(pay.get("min_date") == "2026-10-16" and pay.get("max_date") == "2027-10-16" and pay.get("locale") == "en"
      and pay.get("submit") == "submit" and pay.get("default_from") == "2026-10-17",
      "picker bounds: today to a year out, opening on tomorrow, as the planner's")
check(d1["bot_message"].startswith("What are your check-in and check-out dates?"),
      "the question text comes with the picker")
nodates = converse(["Hotel in Rome Nov 3 to Nov 7, 1 room"])[0]
check(nodates["widget"] is None, "no picker when the dates are not being asked")
check(converse(["Hotel in Rome Nov 3 to Nov 7, 2 adults, no kids, 1 room"])[0]["widget"] is None,
      "no picker once the form is complete")

SUBMIT = lambda a, b: {"action_id": "submit_dates", "value": {"from": a, "to": b, "nights": 4},
                       "submitted_value": {"from": a, "to": b, "nights": 4}}
hp = converse(["I need a hotel in Rome", ("", SUBMIT("2026-11-03", "2026-11-07")), "2 adults, no kids, 1 room"])
check(hp[1]["state"].get("start_date") == "2026-11-03" and "dates" not in hp[1]["asked"]
      and form(hp[-1])["payload"]["criteria"]["checkIn"] == "2026-11-03"
      and form(hp[-1])["payload"]["criteria"]["checkOut"] == "2026-11-07",
      "the picker's submit fills check-in and check-out")
fr = converse(["Flight from SFO to Lisbon, 1 adult, no kids", "round trip", ("", SUBMIT("2026-11-10", "2026-11-20"))])
check(fr[0]["asked"] == ["trip_type"] and fr[1]["widget"] and "fly back" in fr[1]["bot_message"]
      and form(fr[-1])["payload"]["criteria"].get("returnDate") == "2026-11-20",
      "flight-only: trip type first, then the picker; its submit fills departure and return")
fo = converse(["Flight from SFO to Lisbon, 1 adult, no kids", "one way", ("", SUBMIT("2026-11-10", "2026-11-14"))])
check(form(fo[-1])["payload"]["criteria"].get("departDate") == "2026-11-10"
      and "returnDate" not in form(fo[-1])["payload"]["criteria"],
      "one way: the picker's start is the departure, its end is ignored")
bp = converse(["Flight and hotel in Rome from SFO, 2 adults, no kids, 1 room", ("", SUBMIT("2026-11-03", "2026-11-07"))])
check([(f["payload"]["criteria"].get("checkIn") or f["payload"]["criteria"].get("departDate")) for f in bp[-1]["forms"]]
      == ["2026-11-03", "2026-11-03"], "combined trip: one picker fills both forms' dates")
past_pick = converse(["I need a hotel in Rome", ("", SUBMIT("2026-10-01", "2026-10-05"))])[-1]
check("in the past" in past_pick["bot_message"] and past_pick["widget"], "a past range from the picker is refused and the picker shown again")
rt = converse(["Flights from SFO to Lisbon on Nov 10 for 2 adults, no kids", "round trip"])[-1]
check(rt["asked"] == ["return_date"] and (rt["widget"] or {}).get("payload", {}).get("default_from") == "2026-11-10",
      "asking only the return date shows the picker opening on the departure")

# ── Darya's round 3 (adiona/frontend#55, 2026-10-18) ─────────────────────
# Her prod run 2026-10-18 02:06-02:11Z, replayed with what the model returned. For the
# airport answer the model gave a destination text AND/OR the code; all three shapes.
PICK_SHAPES = {
    "text + code": {"destination": {"text": "Heathrow Airport (LHR)", "kind": "airport"}, "airport_code": "LHR"},
    "text only": {"destination": {"text": "Heathrow Airport (LHR)", "kind": "airport"}},
    "name only": {"destination": {"text": "Heathrow", "kind": "airport"}},
}
for shape, pick_patch in PICK_SHAPES.items():
    run = converse([
        "i want to travel to Europe", "both", "London", "Heathrow Airport (LHR)", "From San Francisco",
        ("", {"action_id": "submit_dates", "submitted_value": {"from": "2026-10-19", "to": "2026-10-23", "nights": 4}}),
        "2 adults only, need one room"],
        scripted({}, {"intent": "both"}, {"destination": {"text": "London", "kind": "city"}}, pick_patch,
                 {"origin": {"text": "San Francisco", "kind": "city"}}, {}, {"adults": 2, "children_count": 0, "rooms": 1}))
    # 1. the origin first, alone; the dates (with the picker) after the user replies
    check(run[3]["asked"] == ["origin"] and run[3]["bot_message"] == "Which city or airport are you flying from?"
          and run[3]["widget"] is None,
          "[%s] after the airport, the origin is asked on its own, with no picker: %r" % (shape, run[3]["bot_message"]))
    check(run[4]["asked"] == ["dates"] and (run[4]["widget"] or {}).get("widget_type") == "date_range_picker"
          and run[4]["bot_message"] == "What are your travel dates: when do you leave, and when do you come back?",
          "[%s] then the dates, on their own, with the date picker" % shape)
    # 2. the hotel destination is the city, the flight keeps the airport
    forms = {f["widget_type"]: f["payload"]["criteria"] for f in run[-1]["forms"]}
    check(forms.get("hotel_search_form", {}).get("destination") == "London"
          and forms.get("flight_search_form", {}).get("destination") == "LHR",
          "[%s] hotel destination is the city (London), flight destination the airport (LHR): %s"
          % (shape, {k: v.get("destination") for k, v in forms.items()}))

# The dates are never asked together with another question, in any conversation here.
paired = [r["asked"] for conv in (hotel, kids, trip, fix, switch, combo, both_run, add_hotel, hp, fr, fo, bp)
          for r in conv if set(r["asked"]) & {"dates", "return_date"} and len(r["asked"]) > 1]
check(not paired, "the dates (and the return date) are always asked on their own: %s" % paired[:3])
check(all((r["widget"] is not None) == bool(set(r["asked"]) & {"dates", "return_date"})
          for conv in (hotel, combo, both_run, hp, fr) for r in conv),
      "the date picker comes exactly with the dates question")

# Airports given as the hotel's destination become their city.
for text, city in (("JFK", "New York"), ("Charles de Gaulle Airport", "Paris"), ("Heathrow Airport (LHR)", "London")):
    h = converse(["hotel please"], scripted({"intent": "hotel", "destination": {"text": text, "kind": "airport"},
                                             "check_in": "2026-11-03", "check_out": "2026-11-07", "adults": 2,
                                             "children_count": 0, "rooms": 1}))[-1]
    check(form(h)["payload"]["criteria"].get("destination") == city,
          "a hotel 'at %s' searches the city %s" % (text, city))
again = converse(["Flight from SFO to London on Nov 10, one way, 1 adult, no kids", "London"])[-1]
check(again["asked"] == ["airport:destination"], "re-typing the city does not pick one of its airports")

# ── The step as the playbook runs it ─────────────────────────────────────

head, body = code.split("# ── The turn ", 1)


def run_step(text, prior=None, payload=None, llm_read=None):
    g = {"thread_path": "chat_threads/chat-t1", "event_payload": dict(payload or {}, text=text),
         "input_event": {"type": "user_message", "payload": {"text": text}},
         "loaded_state": {"found": bool(prior), "document": {"data": prior} if prior else None},
         "relation_docs": [{"path": "user_thread_map/abc", "doc": {"uid": "u"}, "merge": True}],
         "llm_enabled": llm_read is not None, "llm_model": "gemini-3.8-flash", "llm_provider": "vertex",
         "vertex_project": "p", "vertex_region": "global", "today_override": TODAY.isoformat()}
    exec(head, g)
    if llm_read:
        g["llm_read"] = llm_read
    exec("# ── The turn " + body, g)
    return g["result"]


r1 = run_step("I need a hotel in Rome")
check(r1["forms"] == [] and r1["asked"] == ["dates"]
      and (r1["render"] or {}).get("widget_type") == "date_range_picker",
      "step: asks while incomplete; asking the dates renders the date picker, no form")
check([d["path"] for d in r1["turn_docs"]] == ["chat_threads/chat-t1/slot_state/intake", "user_thread_map/abc"],
      "step: saves its own slot document plus the relation edge")
check([e["event"]["type"] for e in r1["turn_events"]] == ["user_message", "agent_slot_update", "agent_chat", "agent_widget_emit"]
      and r1["turn_events"][-1]["event"]["payload"]["envelope"] == r1["render"],
      "step: events are the message, the state update, the question and the saved date picker")
r2 = run_step("Nov 3 to Nov 7, 2 adults, no kids, 1 room", prior=r1["intake_state"])
check(r2["render"] == form(r2) and r2["render"]["widget_type"] == "hotel_search_form",
      "step: once complete, render is the form")
check([e["event"]["type"] for e in r2["turn_events"]][-1] == "agent_widget_emit"
      and r2["turn_events"][-1]["event"]["payload"]["envelope"] == r2["render"], "step: the form is saved as a widget event")


def broken(*args):
    raise OSError("metadata server unreachable")


r3 = run_step("Hotel in Rome Nov 3 to Nov 7, 2 adults, no kids, 1 room", llm_read=broken)
check(r3["forms"] and not r3["llm"]["used"] and "OSError" in r3["llm"]["fallback_reason"],
      "step: a model failure falls back to the rule reader and says so")

if failures:
    sys.exit("%d failure(s)" % len(failures))
