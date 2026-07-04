#!/usr/bin/env python3
"""Regression test: the guided sequence advances past flight selection even when
the Duffel booking failed (empty order), instead of dead-ending on a premature
itinerary_summary whose Confirm finalizes an empty trip.

Reproduces noetl/ai-meta prod exec 331868846568775680 ("Trip to Paris" →
picked flight AA SFO→LBG, create_order returned an empty order → order_id "" →
routing fell through to `elif picked_flight: summary` → Confirm → trip_map).

Runs the real embedded `extract_turn` code (no external calls).
"""
import sys, yaml, copy

PLAYBOOK = "playbooks/itinerary-planner.yaml"
doc = yaml.safe_load(open(PLAYBOOK))
extract = next(s for s in doc["workflow"] if s.get("step") == "extract_turn")
code = extract["tool"]["code"]


def run(event_type, payload, loaded_slot_state):
    g = {
        "thread_path": "chat_threads/test",
        "event_type": event_type,
        "event_payload": payload,
        "input_event": {},
        "user_uid": "guest",
        "loaded_slot_state": {"data": copy.deepcopy(loaded_slot_state)},
        "ai_provider": "openai",
        "llm_extraction_model": "gpt-4o",
        "openai_api_key": "",
        "anthropic_api_key": "",
        "flight_provider": "duffel",
        "duffel_env": "test",
    }
    exec(compile(code, PLAYBOOK + ":extract_turn", "exec"), g)
    return g["result"]


# Slot after: place→dates→party→flight search→flight pick, but the Duffel
# create_order returned an empty order (the prod failure).  order_id "".
FLIGHT_PICKED_ORDER_FAILED = {
    "region": {"label": "Paris", "city_code": "PAR", "country_code": "FR", "kind": "city"},
    "region_label": "Paris", "region_city_code": "PAR",
    "region_center": {"lat": "48.8566", "lng": "2.3522"},
    "check_in_date": "2026-07-29", "check_out_date": "2026-08-02", "nights": 4,
    "party": {"adults": 2, "children": [], "rooms": 1},
    "places_seen": ["ChIJD7fiBh9u5kcRYJSMaMOCCwQ"], "total_results_seen": 10,
    "flight_search_results": ["off_1", "off_2"],
    "flight_offers": [{"offer_id": "off_1", "carriers": ["AA"], "price": {"currency": "USD", "total": "678.02"}}],
    "picked_flight_offer_id": "off_1",
    "order_id": "", "booking_reference": "",
    "last_order": {"order_id": "", "total_amount": "0.00", "slices": [], "passengers": []},
}

FORWARD_TAP = ("user_widget_cta_click", {"action_id": "view_full"})

failures = []


def check(name, r, want_kind, want_tool=None):
    kind = r["render_intent"].get("kind")
    tool = r["first_tool"]
    ok = kind == want_kind and (want_tool is None or tool == want_tool)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: intent={kind} tool={tool!r}")
    if not ok:
        failures.append(f"{name}: got intent={kind} tool={tool!r}, want intent={want_kind} tool={want_tool!r}")
    return r["slot_state"]


# (1) THE BUG: flight picked, order failed (order_id "") → must advance to
# hotels, NOT a premature summary.  Pre-fix this rendered {"kind": "summary"}.
s = check("1 picked flight + FAILED order -> show_hotels (was premature summary)",
          run(*FORWARD_TAP, FLIGHT_PICKED_ORDER_FAILED),
          "show_hotels", "mcp/hotelbeds.search_hotels")

# (2) hotels searched -> activities
s2 = copy.deepcopy(FLIGHT_PICKED_ORDER_FAILED)
s2["hotel_search_results"] = ["hb_1", "hb_2"]
check("2 hotels present -> show_activities",
      run(*FORWARD_TAP, s2), "show_activities", "mcp/hotelbeds-activities.search_activities")

# (2b) hotels returned EMPTY (sentinel) still advances to activities
s2b = copy.deepcopy(FLIGHT_PICKED_ORDER_FAILED)
s2b["hotel_search_results"] = ["__searched__"]
check("2b hotels empty-sentinel -> show_activities (no re-search loop)",
      run(*FORWARD_TAP, s2b), "show_activities", "mcp/hotelbeds-activities.search_activities")

# (3) activities searched -> transfers
s3 = copy.deepcopy(s2)
s3["activity_search_results"] = ["ac_1"]
check("3 activities present -> show_transfers",
      run(*FORWARD_TAP, s3), "show_transfers", "mcp/hotelbeds-transfers.search_transfers")

# (4) transfers searched -> the real summary (end of the guided walk)
s4 = copy.deepcopy(s3)
s4["transfer_search_results"] = ["tr_1"]
check("4 full walk done -> summary", run(*FORWARD_TAP, s4), "summary")

# (5) Confirm on the (real, end-of-walk) summary -> trip_map finalize
check("5 Confirm at summary -> trip_map",
      run("user_widget_cta_click", {"action_id": "confirm"}, s4), "trip_map")

# (6) A booked order still walks the same sequence (no regression for success)
s6 = copy.deepcopy(FLIGHT_PICKED_ORDER_FAILED)
s6["order_id"] = "ord_real"
s6["booking_reference"] = "ABC123"
check("6 successful order still -> show_hotels",
      run(*FORWARD_TAP, s6), "show_hotels", "mcp/hotelbeds.search_hotels")

print()
if failures:
    print("FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("ALL FLOW-ADVANCE SCENARIOS PASS")
