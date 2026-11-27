#!/usr/bin/env python3
"""The chat Book CTA hands off to the Stripe checkout only when the flag says so.

Runs the real `extract_turn` and `render_widget_chat` decision code of
itinerary-planner (no network: the LLM reader falls back to the heuristic).

  payments_checkout_mode off (default)  -> unchanged: the direct TEST booking
                                           (mcp/duffel.create_order /
                                           mcp/hotelbeds.book_hotel)
  canary                                -> checkout only for a uid in
                                           payments_canary_uids
  on                                    -> checkout for every signed-in uid
  anything else                         -> treated as off

A checkout turn requests NO provider tool, so nothing is booked or paid from the
chat path; the SPA's checkout (muno/playbooks/payments) does that after the card
is authorised.
"""
import copy
import sys

import yaml

PLAYBOOK = "playbooks/itinerary-planner.yaml"
doc = yaml.safe_load(open(PLAYBOOK))
steps = {s.get("step"): s for s in doc["workflow"]}
EXTRACT = steps["extract_turn"]["tool"]["code"]
failures = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


BASE = {
    "region": {"label": "Paris", "city_code": "PAR", "country_code": "FR", "kind": "city"},
    "region_label": "Paris", "region_city_code": "PAR",
    "check_in_date": "2026-07-29", "check_out_date": "2026-08-02", "nights": 4,
    "party": {"adults": 2, "children": [], "rooms": 1},
    "places_seen": ["p1"], "total_results_seen": 1,
}
HOTEL_STATE = dict(BASE, hotel_search_results=["h1"], hotel_offers=[
    {"hotel_id": "h1", "name": "Hotel Test", "rate_key": "RK-1", "currency": "EUR", "min_rate": "240.00"}])
FLIGHT_STATE = dict(BASE, flight_origin="SFO", flight_destination="CDG",
                    flight_search_results=["off_1"], order_id="")


def run(state, action_id, mode, uids=(), uid="auth0|alice", submitted=None, code=None):
    g = {
        "thread_path": "chat_threads/test", "event_type": "user_widget_cta_click",
        "event_payload": {"action_id": action_id, "submitted_value": submitted or {}},
        "input_event": {}, "user_uid": uid,
        "loaded_slot_state": {"data": copy.deepcopy(state)},
        "ai_provider": "openai", "llm_extraction_model": "gpt-4o",
        "openai_api_key": "", "anthropic_api_key": "", "flight_provider": "duffel",
        "duffel_env": "test", "llm_extraction_enabled": False, "default_origin": "SFO",
        "vertex_project": "p", "vertex_region": "global", "llm_provider": "vertex",
        "anthropic_model": "claude-haiku-5-5", "anthropic_secret_name": "x",
        "anthropic_workspace_id": "w", "claude_thinking": "disabled",
        "payments_checkout_mode": mode,
        "payments_canary_uids": uids if isinstance(uids, str) else list(uids),
    }
    exec(compile(code or EXTRACT, PLAYBOOK + ":extract_turn", "exec"), g)
    r = g["result"]
    if code is not None or mode == "__full__":
        return r
    tools = [t.get("tool") for t in (r.get("tool_requests") or [])]
    return tools, r.get("render_intent") or {}


def _stable(r):
    # The decision outputs, minus per-run ids and timestamps.
    return {"tool_requests": r.get("tool_requests"), "render_intent": r.get("render_intent"),
            "slot_updates": r.get("slot_updates")}


# ── bindings ────────────────────────────────────────────────────────────────
inp = steps["extract_turn"]["tool"]["input"]
check(inp.get("payments_checkout_mode") == "{{ workload.payments_checkout_mode | default('off') }}",
      "extract_turn binds payments_checkout_mode, default off")
check("payments_canary_uids" in inp, "extract_turn binds payments_canary_uids")

# ── hotel Book CTA ──────────────────────────────────────────────────────────
HB = "book_hotel:h1"
tools, intent = run(HOTEL_STATE, HB, "off")
check(tools == ["mcp/hotelbeds.book_hotel"] and intent.get("kind") == "hotel_confirmation",
      "hotel, off: unchanged direct HotelBeds TEST booking")
tools, intent = run(HOTEL_STATE, HB, "canary", uids=["auth0|bob"])
check(tools == ["mcp/hotelbeds.book_hotel"], "hotel, canary, uid not allowlisted: direct booking")
tools, intent = run(HOTEL_STATE, HB, "canary", uids=["auth0|alice"])
co = intent.get("checkout") or {}
check(tools == [] and intent.get("kind") == "payment_checkout", "hotel, canary, allowlisted: checkout, no tool")
check(co.get("kind") == "hotel" and co.get("rate_key") == "RK-1" and co.get("title") == "Hotel Test",
      "hotel checkout carries rate_key and the hotel name")
check(co.get("party") == {"adults": 2, "children": 0, "rooms": 1}, "hotel checkout carries the party")
tools, intent = run(HOTEL_STATE, HB, "canary", uids="auth0|alice,auth0|carol")
check(intent.get("kind") == "payment_checkout", "canary list may arrive as a comma string")
tools, intent = run(HOTEL_STATE, HB, "on")
check(tools == [] and intent.get("kind") == "payment_checkout", "hotel, on: checkout")
tools, intent = run(HOTEL_STATE, HB, "on", uid="guest")
check(tools == [] and intent.get("kind") == "payment_checkout",
      "hotel, on: a guest also gets the checkout card (create_checkout refuses guests)")
tools, intent = run(HOTEL_STATE, HB, "canary", uids=["guest"], uid="guest")
check(tools == ["mcp/hotelbeds.book_hotel"], "canary never matches the guest uid")
tools, intent = run(HOTEL_STATE, HB, "ON-ish")
check(tools == ["mcp/hotelbeds.book_hotel"], "unrecognised mode is off")

# ── flight Book CTA ─────────────────────────────────────────────────────────
FB = "book_offer:off_1"
tools, intent = run(FLIGHT_STATE, FB, "off")
check(tools == ["mcp/duffel.create_order"] and intent.get("kind") == "order_confirmation",
      "flight, off: unchanged direct Duffel TEST order")
tools, intent = run(FLIGHT_STATE, FB, "on")
co = intent.get("checkout") or {}
check(tools == [] and intent.get("kind") == "payment_checkout", "flight, on: checkout, no Duffel order")
check(co.get("kind") == "flight" and co.get("offer_id") == "off_1" and co.get("title") == "SFO to CDG",
      "flight checkout carries offer_id and route title")
tools, intent = run(FLIGHT_STATE, FB, "canary", uids=["auth0|bob"])
check(tools == ["mcp/duffel.create_order"], "flight, canary, not allowlisted: direct order")

# ── off is the pre-flag planner, decision for decision ─────────────────────
# Compared against git `origin/main` when the base copy is reachable.
import os
import subprocess
try:
    base_src = subprocess.run(["git", "show", "origin/main:" + PLAYBOOK], capture_output=True,
                              text=True, check=True).stdout
    base_code = next(s for s in yaml.safe_load(base_src)["workflow"]
                     if s.get("step") == "extract_turn")["tool"]["code"]
except Exception:
    base_code = None
if base_code and "payments_checkout_mode" not in base_code:
    for label, state, act in (("hotel", HOTEL_STATE, HB), ("flight", FLIGHT_STATE, FB)):
        new = _stable(run(state, act, "off", code=EXTRACT))
        old = _stable(run(state, act, "off", code=base_code))
        check(new == old, "%s, off: tool_requests/render_intent/slot_updates identical to origin/main" % label)
else:
    print("SKIP origin/main comparison (base not reachable or already flagged)")

# ── render: the envelope is the payment_checkout widget ────────────────────
render = steps["render_widget_chat"]["tool"]["code"]
check('elif intent == "payment_checkout":' in render and '_env("payment_checkout"' in render,
      "render_widget_chat renders payment_checkout")

if failures:
    print("\n%d failure(s)" % len(failures))
    sys.exit(1)
print("\nALL PAYMENTS FLAG SCENARIOS PASS")
