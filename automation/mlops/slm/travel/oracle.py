"""Travel-domain deterministic oracle — the SLM's labeling floor.

This module is the *deterministic engine* the travel-SLM RFC (noetl/travel#63,
RFC ``docs/rfc/travel-slm.md`` §2/§5) refers to: a rule-based reimplementation
of the two OpenAI passes the Muno itinerary-planner declares —

  * ``extract``  — (user event, slot_state, thread) -> {slot_updates,
                   tool_requests, render_intent}
  * ``render``   — (slot_state, extraction, tool_summary, render_intent) ->
                   {bot_message, widgets[]}

It is derived from the deterministic Python the planner runs today
(``playbooks/itinerary-planner.yaml``, the steps that emit
``llm_contract.fallback_used: true``).  The planner keeps the logic inline;
this module lifts the *contract* into one reusable place so the MLOps
``dataset_build`` / ``eval`` playbooks can call it as the label source without
spending OpenAI tokens.  Wiring the planner itself to delegate to this shared
module (so the two cannot drift) is a tracked follow-up — for Phase A the
contract is reproduced from the documented spec + the planner survey.

Pure stdlib.  No I/O, no network.  Importable by the generic
``automation/mlops/slm`` engine (config points at ``module`` + the two entry
functions ``extract`` and ``render``), and runnable directly for a sanity
check::

    python3 oracle.py --selftest

Contract sources:
  * playbooks/agent/system_prompt_extraction.md
  * playbooks/agent/system_prompt_chat.md
  * playbooks/widget-contract/*.schema.json   (the 24 widget types + envelope)
"""

import re

# ── domain vocab (the enums the contract closes over) ──────────────────────

# city label -> (city_code, country_code, departure-airport IATA used for flights)
CITY_MAP = {
    "miami": {"label": "Miami", "city_code": "MIA", "country_code": "US"},
    "paris": {"label": "Paris", "city_code": "PAR", "country_code": "FR"},
    "boston": {"label": "Boston", "city_code": "BOS", "country_code": "US"},
    "new york": {"label": "New York", "city_code": "NYC", "country_code": "US"},
    "nyc": {"label": "New York", "city_code": "NYC", "country_code": "US"},
    "london": {"label": "London", "city_code": "LON", "country_code": "GB"},
    "rome": {"label": "Rome", "city_code": "ROM", "country_code": "IT"},
    "tokyo": {"label": "Tokyo", "city_code": "TYO", "country_code": "JP"},
}

# the exact tool ids the extractor may emit (routing arcs match verbatim)
TOOL_GOOGLE_PLACES = "mcp/google-places.search_text"
TOOL_DUFFEL_OFFERS = "mcp/duffel.search_offers"
TOOL_DUFFEL_ORDER = "mcp/duffel.create_order"
TOOL_AMADEUS_HOTELS = "mcp/amadeus.search_hotels"
TOOL_VOCAB = [
    TOOL_GOOGLE_PLACES,
    TOOL_DUFFEL_OFFERS,
    TOOL_DUFFEL_ORDER,
    TOOL_AMADEUS_HOTELS,
]

# render_intent.kind enum (bridge between the two passes)
RENDER_INTENT_VOCAB = [
    "collect_missing",
    "show_places",
    "show_flights",
    "show_hotels",
    "flight_detail",
    "order_confirmation",
    "order_detail",
    "summary",
    "summarize",
    "calendar_live",
    "clarify",
    "error",
]

DEFAULT_ORIGIN = "SFO"


# ── slot-extraction helpers (regex / keyword hints) ────────────────────────

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_PARTY_NUM_RE = re.compile(r"(\d+)\s+(adult|traveller|traveler|people|guest)")


def _text_of(event_payload):
    if not isinstance(event_payload, dict):
        return ""
    for key in ("text", "message", "label"):
        v = event_payload.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def _city_hint(text):
    low = text.lower()
    for needle, region in CITY_MAP.items():
        if needle in low:
            return dict(region, kind="city")
    return None


def _date_hint(text):
    dates = _DATE_RE.findall(text)
    if len(dates) >= 2:
        return dates[0], dates[1]
    if "next month" in text.lower():
        return "2026-07-10", "2026-07-14"
    return None


def _party_hint(text):
    low = text.lower()
    if "couple" in low:
        return {"rooms": 1, "adults": 2, "children": []}
    m = _PARTY_NUM_RE.search(low)
    if m:
        return {"rooms": 1, "adults": int(m.group(1)), "children": []}
    return None


def _nights(check_in, check_out):
    try:
        from datetime import date

        a = date.fromisoformat(check_in)
        b = date.fromisoformat(check_out)
        return max((b - a).days, 0)
    except Exception:
        return 0


def _ready(slot):
    return bool(slot.get("region")) and bool(slot.get("check_in_date")) and bool(
        slot.get("party")
    )


def _missing(slot):
    miss = []
    if not slot.get("region"):
        miss.append("region")
    if not slot.get("check_in_date"):
        miss.append("dates")
    if not slot.get("party"):
        miss.append("party")
    return miss


# ── extraction pass ────────────────────────────────────────────────────────

def extract(turn):
    """(event, slot_state, thread) -> {slot_updates, tool_requests, render_intent}.

    ``turn`` keys: event_type, event_payload, slot_state (current), and the
    runtime constants duffel_env / flight_provider (optional).
    """
    slot = dict(turn.get("slot_state") or {})
    event_type = turn.get("event_type", "user_message")
    event_payload = turn.get("event_payload") or {}
    text = _text_of(event_payload)
    low = text.lower()
    duffel_env = turn.get("duffel_env", "test")

    updates = {}

    # ── slot extraction from the new event ──
    if event_type == "user_widget_submit":
        val = event_payload.get("submitted_value", event_payload.get("value"))
        action_id = event_payload.get("action_id", "")
        if isinstance(val, dict):
            if {"from", "to"} <= set(val):
                updates["check_in_date"] = val["from"]
                updates["check_out_date"] = val["to"]
                updates["nights"] = val.get("nights", _nights(val["from"], val["to"]))
            if "adults" in val:
                updates["party"] = {
                    "rooms": val.get("rooms", 1),
                    "adults": val["adults"],
                    "children": val.get("children", []),
                }
            if {"id", "label"} <= set(val):
                hit = _city_hint(val["label"]) or {
                    "label": val["label"],
                    "city_code": val["id"],
                    "country_code": "US",
                    "kind": val.get("kind", "city"),
                }
                updates["region"] = hit
        if action_id.startswith("date:"):
            pass  # handled by submitted_value above
    elif event_type == "user_widget_cta_click":
        action_id = event_payload.get("action_id", "")
        if action_id.startswith("pick_offer:") or action_id.startswith("view_offer:"):
            updates["picked_flight_offer_id"] = action_id.split(":", 1)[1]
        elif action_id.startswith("pick_hotel:") or action_id.startswith("hotel:"):
            updates["picked_hotel_id"] = action_id.split(":", 1)[1]
    else:  # user_message — free text
        hit = _city_hint(text)
        if hit and not slot.get("region"):
            updates["region"] = hit
        dh = _date_hint(text)
        if dh and not slot.get("check_in_date"):
            updates["check_in_date"], updates["check_out_date"] = dh
            updates["nights"] = _nights(dh[0], dh[1])
        ph = _party_hint(text)
        if ph and not slot.get("party"):
            updates["party"] = ph

    # apply updates onto a working copy for the routing decision
    merged = dict(slot)
    merged.update(updates)

    # intent flags from the text
    wants_calendar = ("show" in low or "view" in low) and (
        "schedule" in low or "calendar" in low
    )
    wants_order = any(w in low for w in ("book", "order", "confirm", "purchase")) or (
        event_type == "user_widget_cta_click"
        and event_payload.get("action_id", "").startswith("book_offer:")
    )
    view_flight_now = "details" in low and bool(merged.get("picked_flight_offer_id"))

    region = merged.get("region") or {}
    city_code = region.get("city_code", "")
    tool_requests = []
    render_intent = {"kind": "summarize"}

    # ── routing decision tree (planner order) ──
    if not _ready(merged):
        render_intent = {"kind": "collect_missing", "missing": _missing(merged)}
    elif wants_calendar:
        render_intent = {"kind": "calendar_live"}
    elif region and not merged.get("places_seen"):
        tool_requests = [
            {
                "tool": TOOL_GOOGLE_PLACES,
                "arguments": {"query": region.get("label", ""), "max_results": 5},
            }
        ]
        render_intent = {"kind": "show_places"}
    elif _ready(merged) and not merged.get("flight_search_results"):
        adults = (merged.get("party") or {}).get("adults", 1)
        tool_requests = [
            {
                "tool": TOOL_DUFFEL_OFFERS,
                "arguments": {
                    "origin": DEFAULT_ORIGIN,
                    "destination": city_code,
                    "departure_date": merged.get("check_in_date"),
                    "adults": adults,
                    "cabin_class": "economy",
                    "duffel_env": duffel_env,
                },
            }
        ]
        render_intent = {"kind": "show_flights"}
    elif view_flight_now:
        render_intent = {"kind": "flight_detail"}
    elif merged.get("picked_flight_offer_id") and wants_order and not merged.get("order_id"):
        tool_requests = [
            {
                "tool": TOOL_DUFFEL_ORDER,
                "arguments": {
                    "offer_id": merged["picked_flight_offer_id"],
                    "passengers": [{"given_name": "Alex", "family_name": "Traveller"}],
                    "duffel_env": duffel_env,
                },
            }
        ]
        render_intent = {"kind": "order_confirmation"}
    elif merged.get("picked_flight_offer_id") and not merged.get("hotel_search_results"):
        tool_requests = [
            {
                "tool": TOOL_AMADEUS_HOTELS,
                "arguments": {
                    "cityCode": city_code,
                    "checkInDate": merged.get("check_in_date"),
                    "checkOutDate": merged.get("check_out_date"),
                    "adults": (merged.get("party") or {}).get("adults", 1),
                    "amadeus_env": turn.get("amadeus_env", "test"),
                },
            }
        ]
        render_intent = {"kind": "show_hotels"}
    elif merged.get("picked_flight_offer_id") and merged.get("picked_hotel_id"):
        render_intent = {"kind": "summary"}
    else:
        render_intent = {"kind": "summarize"}

    return {
        "slot_updates": updates,
        "tool_requests": tool_requests,
        "render_intent": render_intent,
    }


# ── deterministic tool-response fixtures (stand-ins for live MCP calls) ─────
# dataset_build does not call the live MCP providers in Phase A; the renderer
# needs a normalized tool summary to build schema-valid widgets.  These are
# deterministic fixtures — real provider responses arrive via event-log replay
# (RFC decision #8, a Phase-1 follow-up).

def _fixture_places(region):
    label = region.get("label", "Destination")
    return [
        {
            "place_id": "place_%s_%d" % (region.get("city_code", "X"), i),
            "name": "%s Landmark %d" % (label, i),
            "types": ["tourist_attraction"],
            "photos": ["https://example.com/p%d.jpg" % i],
            "rating": 4.5,
            "rating_count": 1200 + i,
            "address": "%s, %s" % (label, region.get("country_code", "")),
        }
        for i in range(1, 4)
    ]


def _fixture_flights(region, check_in):
    code = region.get("city_code", "MIA")
    return [
        {
            "offer_id": "off_%s_%d" % (code, i),
            "price": {"total": "%d.00" % (450 + i * 30), "currency": "USD"},
            "itineraries": [
                {
                    "duration": "PT6H30M",
                    "segments": [
                        {
                            "departure": {"iata": DEFAULT_ORIGIN, "at": "%sT08:00:00" % check_in},
                            "arrival": {"iata": code, "at": "%sT14:30:00" % check_in},
                            "carrier": "AA",
                            "flight_number": "AA%d" % (100 + i),
                            "duration": "PT6H30M",
                            "stops": 0,
                        }
                    ],
                }
            ],
            "carriers": ["AA"],
            "duration": "PT6H30M",
            "stops": 0,
            "validating_airline": "AA",
        }
        for i in range(1, 4)
    ]


def _fixture_hotels(region):
    label = region.get("label", "Destination")
    return [
        {
            "hotel_id": "hotel_%s_%d" % (region.get("city_code", "X"), i),
            "name": "%s Grand Hotel %d" % (label, i),
            "location": {"lat": 25.7 + i * 0.01, "lng": -80.1 - i * 0.01, "city": label},
            "star_rating": 4.0,
            "score": 8.5,
            "score_count": 300 + i,
            "photos": ["https://example.com/h%d.jpg" % i],
            "amenities": ["wifi", "breakfast", "pool"],
            "price_per_night": 180.0 + i * 20,
            "currency": "USD",
            "address": "%s Beach Rd %d" % (label, i),
        }
        for i in range(1, 4)
    ]


def _tool_summary(extraction, slot_state):
    """Build the normalized tool summary the renderer reads, given the
    extractor's first tool and the (post-update) slot state."""
    reqs = extraction.get("tool_requests") or []
    if not reqs:
        return {"ok": True, "tool": "", "data": {}}
    tool = reqs[0]["tool"]
    region = slot_state.get("region") or {}
    if tool == TOOL_GOOGLE_PLACES:
        return {"ok": True, "tool": tool, "data": {"places": _fixture_places(region)}}
    if tool == TOOL_DUFFEL_OFFERS:
        return {
            "ok": True,
            "tool": tool,
            "data": {"offers": _fixture_flights(region, slot_state.get("check_in_date", "2026-07-10"))},
        }
    if tool == TOOL_AMADEUS_HOTELS:
        return {"ok": True, "tool": tool, "data": {"hotels": _fixture_hotels(region)}}
    if tool == TOOL_DUFFEL_ORDER:
        return {
            "ok": True,
            "tool": tool,
            "data": {
                "order_id": "ord_%s" % (slot_state.get("picked_flight_offer_id", "x")),
                "booking_reference": "BR%s" % (slot_state.get("picked_flight_offer_id", "X")[-4:].upper()),
                "total_amount": "510.00",
                "total_currency": "USD",
            },
        }
    return {"ok": True, "tool": tool, "data": {}}


# ── render pass ────────────────────────────────────────────────────────────

def _env(widget_type, variant, payload):
    return {
        "schema_version": 1,
        "widget_type": widget_type,
        "variant": variant,
        "payload": payload,
    }


def render(turn, extraction=None, tool_summary=None):
    """(slot_state, extraction, tool_summary, render_intent) ->
    {bot_message, widgets[]}.

    If ``extraction`` is None it is computed from ``turn`` first; if
    ``tool_summary`` is None a deterministic fixture summary is synthesized for
    the extractor's selected tool (Phase A — no live MCP call)."""
    if extraction is None:
        extraction = extract(turn)
    slot = dict(turn.get("slot_state") or {})
    slot.update(extraction.get("slot_updates") or {})
    if tool_summary is None:
        tool_summary = _tool_summary(extraction, slot)

    intent = (extraction.get("render_intent") or {}).get("kind", "summarize")
    missing = (extraction.get("render_intent") or {}).get("missing", [])
    region = slot.get("region") or {}
    data = (tool_summary or {}).get("data") or {}
    tool_ok = (tool_summary or {}).get("ok", True)

    widgets = []
    bot = "Here is the current itinerary state."

    if not tool_ok and (tool_summary or {}).get("tool"):
        bot = "That provider hiccuped, but the itinerary thread is still intact."
        widgets.append(
            _env(
                "error_card",
                "default",
                {
                    "title": "Provider error",
                    "description": "The travel provider did not respond. Try again.",
                    "retry_action_id": "retry:%s" % tool_summary.get("tool", ""),
                },
            )
        )
    elif intent == "collect_missing":
        if "region" in missing or not missing:
            bot = "Where would you like to go?"
            widgets.append(
                _env(
                    "place_autocomplete_input",
                    "default",
                    {
                        "placeholder": "Search a destination",
                        "suggestions": [
                            {"label": "Miami", "id": "MIA", "kind": "city"},
                            {"label": "Paris", "id": "PAR", "kind": "city"},
                        ],
                        "submit_on_select": True,
                    },
                )
            )
        elif "dates" in missing:
            bot = "When are you travelling?"
            widgets.append(
                _env(
                    "date_range_picker",
                    "compact",
                    {
                        "min_date": "2026-01-01",
                        "max_date": "2026-12-31",
                        "default_from": "2026-07-10",
                        "default_to": "2026-07-14",
                        "locale": "en",
                        "submit": "submit",
                    },
                )
            )
        elif "party" in missing:
            bot = "How many travellers?"
            widgets.append(
                _env(
                    "party_picker",
                    "default",
                    {
                        "rooms_max": 4,
                        "adults_max": 8,
                        "children_max": 6,
                        "allow_child_ages": True,
                    },
                )
            )
    elif intent == "show_places":
        bot = "I found a destination anchor. Next I need dates and travellers."
        widgets.append(
            _env(
                "place_list",
                "default",
                {
                    "title": "Top places in %s" % region.get("label", ""),
                    "items": data.get("places", []),
                },
            )
        )
    elif intent == "show_flights":
        offers = data.get("offers", [])
        bot = "Here is the first flight batch. Book one to create a Duffel test order."
        widgets.append(
            _env(
                "flight_list",
                "default",
                {
                    "title": "Flights to %s" % region.get("label", ""),
                    "items": offers,
                    "total_count": len(offers),
                    "currency": "USD",
                },
            )
        )
    elif intent == "flight_detail":
        offers = data.get("offers") or _fixture_flights(region, slot.get("check_in_date", "2026-07-10"))
        bot = "Here are the flight details."
        widgets.append(_env("flight_card", "default", offers[0]))
    elif intent == "show_hotels":
        hotels = data.get("hotels", [])
        bot = "Hotel options are ready."
        widgets.append(
            _env(
                "hotel_list",
                "default",
                {
                    "title": "Hotels in %s" % region.get("label", ""),
                    "items": hotels,
                    "total_count": len(hotels),
                },
            )
        )
    elif intent in ("order_confirmation", "order_detail"):
        bot = "Your Duffel test order is confirmed."
        widgets.append(
            _env(
                "order_confirmation",
                "default",
                {
                    "order_id": data.get("order_id", "ord_x"),
                    "booking_reference": data.get("booking_reference", "BR0000"),
                    "total_amount": data.get("total_amount", "510.00"),
                    "total_currency": data.get("total_currency", "USD"),
                },
            )
        )
    elif intent == "summary":
        bot = "The itinerary is ready to review."
        widgets.append(
            _env(
                "itinerary_summary",
                "default",
                {
                    "destination": region.get("label", "Destination"),
                    "dates": {
                        "from": slot.get("check_in_date", "2026-07-10"),
                        "to": slot.get("check_out_date", "2026-07-14"),
                    },
                    "traveller_party": slot.get("party", {"adults": 1, "rooms": 1, "children": []}),
                },
            )
        )
        widgets.append(
            _env(
                "calendar_view",
                "compact",
                {"trip_id": "trip_%s" % region.get("city_code", "X"), "editable": False},
            )
        )
    elif intent == "calendar_live":
        bot = "Here is the current trip schedule."
        widgets.append(
            _env(
                "calendar_view",
                "full",
                {"trip_id": "trip_%s" % region.get("city_code", "X"), "editable": True},
            )
        )
    else:  # summarize / fallback
        bot = "Here is the current itinerary state."
        widgets.append(
            _env(
                "itinerary_summary",
                "default",
                {
                    "destination": region.get("label", "Destination"),
                    "dates": {
                        "from": slot.get("check_in_date", "2026-07-10"),
                        "to": slot.get("check_out_date", "2026-07-14"),
                    },
                    "traveller_party": slot.get("party", {"adults": 1, "rooms": 1, "children": []}),
                },
            )
        )

    return {"bot_message": bot, "widgets": widgets}


def run_turn(turn):
    """Convenience: produce both labels for one turn."""
    ex = extract(turn)
    slot = dict(turn.get("slot_state") or {})
    slot.update(ex.get("slot_updates") or {})
    ts = _tool_summary(ex, slot)
    rd = render(turn, ex, ts)
    return {"extract": ex, "render": rd, "tool_summary": ts}


# ── self test ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    if "--selftest" in sys.argv:
        sample = {
            "event_type": "user_message",
            "event_payload": {"text": "Trip to Paris next month for a couple"},
            "slot_state": {},
        }
        out = run_turn(sample)
        print(json.dumps(out, indent=2))
        assert out["extract"]["render_intent"]["kind"] in RENDER_INTENT_VOCAB
        print("OK selftest")
