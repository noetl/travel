#!/usr/bin/env python3
"""Live check of trip-intake's place reading against Vertex (NOT run by CI: it needs
`gcloud auth` and calls the model). Darya's eight inputs from adiona/frontend#55, each
read N times, so the model's variability shows:

  python3 scripts/trip_intake_prompt_eval.py [N]

A line per read: the outcome after the playbook's own rules (a code, a question) and the
airports the model proposed. Expected: Kauai LIH, Maui OGG, Big Island asks KOA/ITO,
Hawaii asks which island, Santorini JTR, Napa offers the nearest (SFO, OAK among them),
Portland asks PDX/PWM, Munich MUC.
"""
import subprocess
import sys
import time
from datetime import date

import yaml

EXPECT = {"Kauai": "LIH", "Maui": "OGG", "Big Island": "ask KOA,ITO", "Hawaii": "ask island", "Santorini": "JTR",
          "Napa": "ask nearest", "Portland": "ask PDX/PWM", "Munich": "MUC"}

doc = yaml.safe_load(open("playbooks/trip-intake.yaml"))
lib = {"_INTAKE_LIBRARY_ONLY": True}
exec({s["step"]: s for s in doc["workflow"]}["intake_turn"]["tool"]["code"], lib)
token = subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode().strip()
lib["_vertex_token"] = lambda: token


def outcome(place):
    seen = {}

    def read(text, state, awaiting, today):
        for attempt in range(5):
            try:
                seen["out"] = lib["llm_read"](text, state, awaiting, today, "gemini-3.8-flash",
                                              "shastaratech-noetl-prod", "global")
                return seen["out"]
            except Exception:  # rate limits and timeouts: back off and retry
                time.sleep(10 * (attempt + 1))
        raise RuntimeError("model unavailable")

    s = lib["run_turn"]({}, "Flights and a hotel in %s" % place, {}, date.today(), read)["state"]
    if s.get("destination_code"):
        got = s["destination_code"]
    elif s.get("destination_options"):
        got = ("ask nearest " if s.get("destination_nearest") else "ask ") + ",".join(s["destination_options"])
    elif s.get("destination_islands"):
        got = "ask island"
    elif s.get("destination_matches"):
        got = "ask " + "/".join(c for m in s["destination_matches"] for c in m["airports"])
    else:
        got = "no airport"
    return got, (seen.get("out", {}).get("destination") or {}).get("airports")


runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
for rep in range(runs):
    for place, want in EXPECT.items():
        try:
            got, proposed = outcome(place)
        except RuntimeError as exc:  # the model stayed unavailable: say so, keep going
            print("ERR  %d %-10s %s" % (rep, place, exc), flush=True)
            continue
        ok = got.startswith(want) or (place == "Napa" and got.startswith("ask nearest") and {"SFO", "OAK"} <= set(got.split()[-1].split(",")))
        print("%s %d %-10s %-30s model proposed %s" % ("ok  " if ok else "MISS", rep, place, got, proposed), flush=True)
        time.sleep(4)
