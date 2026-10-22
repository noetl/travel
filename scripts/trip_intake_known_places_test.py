#!/usr/bin/env python3
"""playbooks/trip-intake.yaml: islands and island groups resolve from a fixed table,
before (and without) the model (adiona/frontend#55). Every case here runs on the rule
reader alone, i.e. as if the model had timed out, so each answer is deterministic.

  * Darya's eight inputs, exactly (Napa, which has no airport and no table entry, needs
    coordinates; they are given as the model would give them);
  * every island and region in data/intake_places.yaml, against that file;
  * namesakes, cities and airports that are not in the table, unchanged;
  * the table wins over the model for a place it knows (Maui stays OGG even when the
    model proposes OGG and JHM).
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
lib = {"_INTAKE_LIBRARY_ONLY": True}
exec({s["step"]: s for s in doc["workflow"]}["intake_turn"]["tool"]["code"], lib)
run_turn, rule_read, KNOWN, BY_CODE = lib["run_turn"], lib["rule_read"], lib["KNOWN_PLACES"], lib["BY_CODE"]
TODAY = date(2026, 10, 21)
DATA = yaml.safe_load(open("data/intake_places.yaml", encoding="utf-8"))


def turn(text, reader=rule_read, state=None):
    return run_turn(state or {}, text, {}, TODAY, reader)


def outcome(r):
    s = r["state"]
    if s.get("destination_code"):
        return s["destination_code"]
    if s.get("destination_options"):
        return ("nearest " if s.get("destination_nearest") else "choose ") + ",".join(s["destination_options"])
    if s.get("destination_islands"):
        return "island? " + ",".join(i["name"] for i in s["destination_islands"])
    if s.get("destination_matches"):
        return "which? " + "/".join(c for m in s["destination_matches"] for c in m["airports"])
    return "asked " + ",".join(r["asked"])


# ── The table is the data file ───────────────────────────────────────────
for island in DATA["islands"]:
    for name in [island["name"]] + island.get("aliases", []):
        entry = lib["known_place"](name)
        if not (entry and entry["kind"] == "island" and entry["airports"] == island["airports"]):
            check(False, "%s is in the table as an island with %s" % (name, island["airports"]))
for region in DATA["regions"]:
    entry = lib["known_place"](region["name"])
    check(entry and entry["kind"] == "region" and [i["name"] for i in entry["islands"]] == region["islands"],
          "%s is in the table as a region of %s" % (region["name"], region["islands"]))
check(len({id(v) for v in KNOWN.values()}) == len(DATA["islands"]) + len(DATA["regions"]),
      "the playbook's table has exactly the file's %d places" % (len(DATA["islands"]) + len(DATA["regions"])))
check(all(c in BY_CODE for i in DATA["islands"] for c in i["airports"]), "every table airport is one the flight form can prefill")

# ── Darya's eight inputs, with no model ──────────────────────────────────
EIGHT = [
    ("Flights and a hotel in Kauai", "LIH", "hotel_area"),
    ("Flights and a hotel in Maui", "OGG", "hotel_area"),
    ("Flights and a hotel in the Big Island", "choose KOA,ITO", "airport:destination"),
    ("Flights and a hotel in Hawaii", "island? Oahu,Maui,Kauai,Big Island", "island:destination"),
    ("Flights and a hotel in Santorini", "JTR", "hotel_area"),
    ("Flights and a hotel in Portland", "which? PDX/PWM", "which:destination"),
    ("Flights and a hotel in Munich", "MUC", None),
]
for text, want, asked in EIGHT:
    r = turn(text)
    check(outcome(r) == want and (asked is None or r["asked"][:1] == [asked]),
          "no model: %s -> %s (asked %s): got %s, asked %s" % (text, want, asked, outcome(r), r["asked"]))
def napa(text, state, awaiting, today):
    out = rule_read(text, state, awaiting, today)
    out["destination"] = {"text": "Napa", "kind": "city", "lat": 38.2975, "lon": -122.2869, "airports": []}
    return out
r = turn("Flights and a hotel in Napa", napa)
check(outcome(r).startswith("nearest") and {"SFO", "OAK"} <= set(outcome(r).split()[1].split(",")),
      "Napa (no airport): the nearest, SFO and OAK among them: %s" % outcome(r))
r = turn("Flights and a hotel in Hawaii")
r2 = run_turn(r["state"], "Maui", {}, TODAY, rule_read)
check(r2["state"].get("destination_code") == "OGG" and r2["asked"] == ["hotel_area"], "Hawaii, then Maui -> OGG, then where to stay")

# ── More islands, regions, aliases, no model ─────────────────────────────
MORE = [
    ("A flight to Oahu", "HNL"), ("A flight to O'ahu", "HNL"), ("A flight to Molokai", "MKK"), ("A flight to Lanai", "LNY"),
    ("A flight to Hawaii Island", "choose KOA,ITO"), ("A flight to the Island of Hawaii", "choose KOA,ITO"),
    ("A flight to Mallorca", "PMI"), ("A flight to Majorca", "PMI"), ("A flight to Menorca", "MAH"), ("A flight to Ibiza", "IBZ"),
    ("A flight to Tenerife", "choose TFS,TFN"), ("A flight to Gran Canaria", "LPA"), ("A flight to Lanzarote", "ACE"),
    ("A flight to Fuerteventura", "FUE"), ("A flight to La Palma", "SPC"), ("A flight to El Hierro", "VDE"),
    ("A flight to Mykonos", "JMK"), ("A flight to Crete", "choose HER,CHQ"), ("A flight to Rhodes", "RHO"),
    ("A flight to Corfu", "CFU"), ("A flight to Zante", "ZTH"), ("A flight to Kefalonia", "EFL"), ("A flight to Thira", "JTR"),
    ("A flight to Sicily", "choose CTA,PMO"), ("A flight to Sardinia", "choose CAG,OLB,AHO"), ("A flight to Corsica", "choose AJA,BIA"),
    ("A flight to Malta", "MLA"), ("A flight to Cyprus", "choose LCA,PFO"), ("A flight to Madeira", "FNC"),
    ("A flight to Aruba", "AUA"), ("A flight to Barbados", "BGI"), ("A flight to Jamaica", "choose MBJ,KIN"),
    ("A flight to Puerto Rico", "SJU"), ("A flight to St Lucia", "UVF"), ("A flight to St. Maarten", "SXM"),
    ("A flight to Curacao", "CUR"), ("A flight to St Barts", "SBH"), ("A flight to Grand Cayman", "GCM"),
    ("A flight to Bali", "DPS"), ("A flight to Phuket", "HKT"), ("A flight to Tahiti", "PPT"), ("A flight to Bora Bora", "BOB"),
    ("A flight to Nantucket", "ACK"),
    ("A flight to the Canary Islands", "island? Tenerife,Gran Canaria,Lanzarote,Fuerteventura,La Palma"),
    ("A flight to the Canaries", "island? Tenerife,Gran Canaria,Lanzarote,Fuerteventura,La Palma"),
    ("A flight to the Balearics", "island? Mallorca,Menorca,Ibiza"),
    ("A flight to the Cyclades", "island? Santorini,Mykonos,Naxos,Paros"),
    ("A flight to the Azores", "island? Sao Miguel,Terceira"),
]
for text, want in MORE:
    got = outcome(turn(text))
    check(got == want, "no model: %s -> %s (got %s)" % (text, want, got))
for text in ("A flight to Formentera", "A flight to Naxos", "A flight to La Gomera", "A flight to Martha's Vineyard"):
    got = outcome(turn(text))
    check(got.startswith("nearest "), "no model: %s (no airport of its own) -> the nearest airports (got %s)" % (text, got))
check(outcome(turn("A flight to Formentera")).startswith("nearest IBZ"), "Formentera's nearest is Ibiza")
check("Formentera has no airport of its own" in turn("A flight to Formentera")["bot_message"], "...and says it has no airport of its own")
r = turn("Maui please, a hotel")
check(r["state"].get("destination", {}).get("text") == "Maui", "a known place named without a cue word is still found")
r = turn("A hotel in Mallorca")
check(r["asked"] == ["hotel_area"] and "Which city or area on Mallorca" in r["bot_message"], "a known island asks where to stay, model or not")

# ── Not in the table: unchanged ──────────────────────────────────────────
for text, want in [("A flight to London", "choose LHR,LGW,STN"), ("A flight to Paris", "choose CDG,ORY"), ("A flight to Munich", "MUC"),
                   ("A flight to Portland, Maine", "PWM"), ("A flight to LHR", "LHR"), ("A flight to Lihue", "LIH")]:
    got = outcome(turn(text))
    check(got == want, "not in the table, unchanged: %s -> %s (got %s)" % (text, want, got))
check(outcome(turn("A flight to Provo")) != "PLS", "Provo is Provo, Utah, not Providenciales")
r = turn("A flight from Honolulu, Hawaii to Munich")
check(r["state"].get("origin_code") == "HNL", "\"Honolulu, Hawaii\" is Honolulu, not the Hawaii region")

# ── The table wins over the model ────────────────────────────────────────
def model(destination):
    def read(text, state, awaiting, today):
        out = rule_read(text, state, awaiting, today)
        out["destination"] = destination
        return out
    return read
r = turn("Flights and a hotel in Maui", model({"text": "Maui", "kind": "island", "airports": ["OGG", "JHM"]}))
check(r["state"].get("destination_code") == "OGG", "the model proposes OGG and JHM for Maui: the table's OGG is used")
r = turn("Flights to Big Island", model({"text": "Big Island", "kind": "island", "airports": ["KOA"]}))
check(outcome(r) == "choose KOA,ITO", "the model proposes KOA only for the Big Island: the traveller still chooses")
r = turn("Flights to Hawaii", model({"text": "Hawaii", "kind": "island", "airports": ["KOA", "ITO"]}))
check(outcome(r).startswith("island?"), "the model reads Hawaii as an island: the table's region asks which island")
r = turn("Flights to the Big Island", model({"text": "the Big Island", "kind": "island", "airports": ["KOA"]}))
check(outcome(r) == "choose KOA,ITO", "\"the Big Island\" as the model wrote it is the table's Big Island")
r = turn("A flight from the Big Island to Munich")
check(r["state"].get("origin_options") == ["KOA", "ITO"] and r["state"].get("destination_code") == "MUC",
      "\"from the Big Island\" is read as the origin, with \"the\"")
r = turn("A hotel at The Grand Maui Resort", model({"text": "The Grand Maui Resort", "kind": "hotel"}))
check(r["state"].get("destination", {}).get("kind") == "hotel", "a hotel's name that contains an island is still a hotel")

if failures:
    sys.exit("%d failure(s)" % len(failures))
