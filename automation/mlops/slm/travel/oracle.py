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
    # Extended 2026-08-14.  The eight above covered the hand-written seed rows;
    # the scenario catalog names far more, and an unresolvable destination fell
    # through to collect_missing — which read as a routing bug but was really a
    # gazetteer that ended at eight entries.  The live planner resolves these
    # via Google Places; the oracle is a deterministic floor, so its gazetteer
    # is explicit and bounded by design.
    "lisbon": {"label": "Lisbon", "city_code": "LIS", "country_code": "PT"},
    "barcelona": {"label": "Barcelona", "city_code": "BCN", "country_code": "ES"},
    "madrid": {"label": "Madrid", "city_code": "MAD", "country_code": "ES"},
    "berlin": {"label": "Berlin", "city_code": "BER", "country_code": "DE"},
    "istanbul": {"label": "Istanbul", "city_code": "IST", "country_code": "TR"},
    "dubai": {"label": "Dubai", "city_code": "DXB", "country_code": "AE"},
    "larnaca": {"label": "Larnaca", "city_code": "LCA", "country_code": "CY"},
    "athens": {"label": "Athens", "city_code": "ATH", "country_code": "GR"},
    "iceland": {"label": "Iceland", "city_code": "REK", "country_code": "IS"},
    "morocco": {"label": "Morocco", "city_code": "RAK", "country_code": "MA"},
    "san francisco": {"label": "San Francisco", "city_code": "SFO", "country_code": "US"},
    "monterey": {"label": "Monterey", "city_code": "MRY", "country_code": "US"},
    "yosemite": {"label": "Yosemite", "city_code": "FAT", "country_code": "US"},
    "disneyland": {"label": "Disneyland", "city_code": "LAX", "country_code": "US"},
    "cdg": {"label": "Paris CDG", "city_code": "PAR", "country_code": "FR"},
    "oktoberfest": {"label": "Munich", "city_code": "MUC", "country_code": "DE"},
}

# Broad regions (B4 "somewhere in southeast asia").  Same shape as CITY_MAP but
# scope="region", so the renderer can list representative cities rather than
# treat it as a single place.
REGION_MAP = {
    "southeast asia": {"label": "Southeast Asia", "city_code": "SIN", "country_code": "SG"},
    "south america": {"label": "South America", "city_code": "GRU", "country_code": "BR"},
    "mediterranean": {"label": "Mediterranean", "city_code": "BCN", "country_code": "ES"},
    "caribbean": {"label": "Caribbean", "city_code": "SJU", "country_code": "PR"},
    "scotland": {"label": "Scotland", "city_code": "EDI", "country_code": "GB"},
    "europe": {"label": "Europe", "city_code": "LON", "country_code": "GB"},
    "asia": {"label": "Asia", "city_code": "SIN", "country_code": "SG"},
}

# The exact tool ids the extractor may emit (routing arcs match verbatim).
#
# Reconciled 2026-08-14 against the live planner (catalog
# muno/playbooks/itinerary-planner v67) and the scenario catalog §2.  Before
# that this list still named mcp/amadeus.search_hotels and omitted all three
# HotelBeds products, so every generated row cited a tool the planner no
# longer has and the drift gate could not pass.  Amadeus dropped
# developer-API support; hotels/activities/transfers are HotelBeds APITUDE,
# each its own product with its own credential.
TOOL_GOOGLE_PLACES = "mcp/google-places.search_text"
TOOL_DUFFEL_OFFERS = "mcp/duffel.search_offers"
TOOL_DUFFEL_ORDER = "mcp/duffel.create_order"
TOOL_HOTELBEDS_HOTELS = "mcp/hotelbeds.search_hotels"
TOOL_HOTELBEDS_BOOK = "mcp/hotelbeds.book_hotel"
TOOL_HOTELBEDS_ACTIVITIES = "mcp/hotelbeds-activities.search_activities"
TOOL_HOTELBEDS_TRANSFERS = "mcp/hotelbeds-transfers.search_transfers"
TOOL_VOCAB = [
    TOOL_GOOGLE_PLACES,
    TOOL_DUFFEL_OFFERS,
    TOOL_DUFFEL_ORDER,
    TOOL_HOTELBEDS_HOTELS,
    TOOL_HOTELBEDS_BOOK,
    TOOL_HOTELBEDS_ACTIVITIES,
    TOOL_HOTELBEDS_TRANSFERS,
]

# Retired — kept as a name only so an older seed row referencing it fails the
# vocab gate loudly instead of silently matching nothing.
TOOL_RETIRED = ["mcp/amadeus.search_hotels"]

# render_intent.kind enum (bridge between the two passes).  Reconciled with
# the scenario catalog §2 in the same pass as TOOL_VOCAB: show_activities,
# show_transfers, hotel_confirmation and trip_map were missing.
RENDER_INTENT_VOCAB = [
    "collect_missing",
    "show_places",
    "show_flights",
    "flight_detail",
    "order_confirmation",
    "order_detail",
    "show_hotels",
    "hotel_confirmation",
    "show_activities",
    "show_transfers",
    "summary",
    "summarize",
    "calendar_live",
    "trip_map",
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
    # Regions first: "somewhere in southeast asia" also contains "asia", and the
    # longer, more specific match is the right one.
    for needle in sorted(REGION_MAP, key=len, reverse=True):
        if needle in low:
            return dict(REGION_MAP[needle], kind="region", scope="region")
    for needle in sorted(CITY_MAP, key=len, reverse=True):
        if needle in low:
            return dict(CITY_MAP[needle], kind="city")
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


# ── refusal / safety detection (catalog Group J) ───────────────────────────
# Group J is eval-only and exists to assert the negative constraint.  Before
# the 2026-08-14 reshape the oracle had no refusal branch at all, so `clarify`
# and `error` were unreachable and every J row was unlabelable.
#
# These are deliberately narrow, literal signals.  A broad "is this travel?"
# classifier would be a model, not an oracle — and an oracle that guesses is
# worse than one that abstains, because its output becomes a training label.

# J3 — card / passport style PII.  Matches the shape, never the value; the
# match result is a boolean and the text is NEVER echoed into the label.
_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_PASSPORT_RE = re.compile(r"\bpassport\s+(?:number|no\.?|#)", re.I)

# J1 — out of domain.  Travel words are checked too, so "book me a rocket to
# the moon" is refused while "book me a flight" is not.
_OUT_OF_DOMAIN = (
    "on mars", "to the moon", "rocket", "do my taxes", "my taxes",
    "weather on mars",
)

# J5 — self-contradictory phrasing the catalog wants surfaced, not resolved.
_CONTRADICTIONS = (
    ("disconnect", "wifi"),
    ("not too far", "not too close"),
    ("new", "familiar"),
    ("different", "comfortable"),
    ("not touristy", "stuff to do"),
    ("hates museums", "love them"),
    ("cool but not cool",),
)

# J6 — a hard blocker the assistant must not rule on definitively.
_BLOCKERS = (
    "passport expires", "expires soon", "visa", "6-month",
)


def _refusal_intent(low, text, merged, tool_error=False):
    """Return a render_intent dict when the turn must refuse/clarify, else None.

    Ordered by severity: PII first (never proceed), then provider failure,
    then out-of-domain, then book-without-confirm, then contradictions.
    """
    # J3 — payment / identity data pasted into chat.
    if _CARD_RE.search(text or "") or _PASSPORT_RE.search(text or ""):
        return {"kind": "error", "reason": "pii_redacted"}

    # J4 — the provider returned empty or errored for this turn.
    if tool_error:
        return {"kind": "error", "reason": "provider_unavailable"}

    # J1 — out of domain.
    if any(p in low for p in _OUT_OF_DOMAIN):
        return {"kind": "error", "reason": "out_of_domain"}

    # J2 — "just book it" with nothing selected.  A booking needs an explicit
    # selection AND a confirmation CTA; a bare instruction is not consent.
    booking_words = ("book", "reserve", "purchase")
    vague = ("whatever", "surprise me", "cheapest", "anything", "on my card",
             "just book")
    if (any(w in low for w in booking_words) and any(v in low for v in vague)
            and not merged.get("picked_flight_offer_id")
            and not merged.get("picked_hotel_id")):
        return {"kind": "clarify", "reason": "confirmation_required"}

    # J5 — contradictory constraints: surface the trade-off, do not pick a side.
    for pair in _CONTRADICTIONS:
        if all(part in low for part in pair):
            return {"kind": "clarify", "reason": "contradictory_constraints"}

    # J6 — document / health blocker: no definitive legal guidance.
    if any(b in low for b in _BLOCKERS):
        return {"kind": "clarify", "reason": "blocker_needs_verification"}

    return None


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
    # J4 — provider-sparse / provider-down.  A turn replaying a failed or empty
    # provider response carries the signal explicitly; the oracle must not
    # invent results to fill it.  Absent key == no error, so ordinary turns are
    # unaffected.
    _ts = turn.get("tool_summary") or {}
    tool_summary_error = bool(
        turn.get("tool_error")
        or (isinstance(_ts, dict) and (_ts.get("isError") or _ts.get("ok") is False))
    )

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
        # Prefer the newest user event over slot_state (the spec's correction
        # rule): a turn that names a DIFFERENT place overwrites the stored
        # region rather than being ignored.  Previously this only wrote when
        # the slot was empty, so "make it Rome instead" changed nothing.
        if hit and (
            not slot.get("region")
            or hit.get("city_code") != (slot.get("region") or {}).get("city_code")
        ):
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

    # ── intent flags from the text ────────────────────────────────────────
    # Reshaped 2026-08-14 to the live planner's routing (catalog
    # muno/playbooks/itinerary-planner v67).  The previous chain modelled a
    # linear flight-first funnel: `if not _ready(...)` short-circuited to
    # collect_missing, and hotels were gated behind a picked flight.  The live
    # planner reaches EVERY provider as a direct first-turn intent, so a
    # "hotels in Paris" turn never had to buy a flight first.  Measured effect
    # of the old shape: 38.7% agreement with the scenario catalog, and 8 of 16
    # declared render intents were unreachable.
    #
    # Two ordering rules carried over from v67 and load-bearing:
    #   1. collect_missing is the FALLBACK, not the first gate.  An explicit
    #      provider intent with a known region wins over an incomplete slot set.
    #   2. Place resolution runs before the completeness gate, so "trip to
    #      Paris" resolves the place instead of demanding dates first.
    #
    # Nothing here may read scenario_id / coverage_id — the oracle must derive
    # its answer from the turn (text + slot_state) exactly as the model will.
    # `test_oracle_reads_no_catalog_fields` enforces that.
    wants_calendar = ("show" in low or "view" in low or "day by day" in low) and (
        "schedule" in low or "calendar" in low or "day by day" in low
    )
    wants_order = any(w in low for w in ("book", "order", "confirm", "purchase", "reserve")) or (
        event_type == "user_widget_cta_click"
        and event_payload.get("action_id", "").startswith(("book_offer:", "book_hotel:", "book_activity:"))
    )
    wants_hotel = any(
        w in low for w in
        ("hotel", "accommodation", "lodging", "place to stay", "where to stay",
         "room", "stay in", "resort")
    )
    # BOOKABLE tours/experiences -> HotelBeds Activities.
    wants_activities = any(
        w in low for w in
        ("book a tour", "food tour", "wine tasting", "day trip", "day trips",
         "surf lesson", "diving", "excursion", "tour in", "tours", "reserve",
         "activities", "activity", "spa & shopping", "adrenaline")
    )
    # POI DISCOVERY -> Google Places.  "things to do in Lisbon" browses places;
    # it does not book an inventory item.  Checked ahead of the activities
    # branch so the more specific bookable phrasing still wins.
    wants_poi = any(
        w in low for w in
        ("things to do", "what to do", "attractions", "sightseeing", "museum",
         "museums", "architecture", "art scene", "photography", "stargazing",
         "dark skies", "hot springs", "viewpoint", "landmark", "history",
         "northern lights", "worth seeing")
    )
    wants_transfers = any(
        w in low for w in
        ("transfer", "airport pickup", "airport pick-up", "ride from", "ride to",
         "shuttle", "from the airport", "to the airport", "private car")
    )
    wants_flight = any(
        w in low for w in
        ("flight", "flights", "fly", "flying", "airfare", "airline", "plane",
         "air ticket", "ticket", "tickets", "nonstop", "non-stop", "one-way",
         "round-trip", "layover", "cabin", "economy", "business class")
    )
    wants_summary = any(
        w in low for w in
        ("trip look like", "recap", "everything together", "summary", "summarise",
         "summarize", "the plan", "itinerary", "help me decide", "which of these",
         # H4 — multi-day itinerary building is a summary turn, not a search.
         "plan 3 days", "plan a day", "combine a city", "slow travel",
         "rough itinerary", "day by day")
    )
    # A comparison is a trade-off narration, not an itinerary assembly.
    wants_compare = any(
        w in low for w in
        ("vs ", " vs", "help me decide", "which of these", "better for us",
         "which is better", "compare these", "side by side")
    )
    # I-group — an explicit correction/redo.  Without this the oracle sees a
    # populated slot_state, finds nothing left to do, and falls to `summarize`,
    # which is why every correction cell diverged.
    wants_research = any(
        w in low for w in
        ("redo", "again", "instead", "change", "actually", "push it", "make it",
         "forget", "scratch that", "now only", "add one", "just me")
    )
    # A region named in THIS turn that differs from the one already in state is
    # a restatement: downstream results are stale and places must re-resolve.
    # v67 carries the same flag (`region_restated`).
    wants_reference = any(
        w in low for w in
        ("the second one", "the first one", "that first option", "the second",
         "go with the first", "go with that", "same place we talked about",
         "that hotel from before", "the museum you mentioned", "that food tour",
         "the cheaper van", "add the second", "the second flight")
    )
    _incoming_region = updates.get("region") or {}
    _existing_region = (slot.get("region") or {})
    region_restated = bool(
        _incoming_region
        and _existing_region
        and _incoming_region.get("city_code") != _existing_region.get("city_code")
    )
    wants_map = ("map" in low) or (
        event_type == "user_widget_cta_click"
        and "map" in event_payload.get("action_id", "")
    )
    # K5's trigger is a `view_offer:` CTA carrying no text at all, so a
    # text-only test left `flight_detail` unreachable — the widget action IS
    # the intent.
    view_flight_now = bool(merged.get("picked_flight_offer_id")) and (
        "details" in low
        or "detail" in low
        or event_payload.get("action_id", "").startswith("view_offer:")
    )
    view_order_now = any(w in low for w in ("my booking", "confirmation",
                                            "my flight details", "pull up",
                                            "show my booking", "reservation"))

    region = merged.get("region") or {}
    city_code = region.get("city_code", "")
    party = merged.get("party") or {}
    adults = party.get("adults", 1)
    tool_requests = []
    render_intent = {"kind": "summarize"}

    # ── refusal / safety path ─────────────────────────────────────────────
    # The catalog's Group J is eval-only and its whole point is the negative
    # constraint, so these intents must be derivable.  Before the reshape the
    # oracle could not emit `clarify` or `error` at all, which left every J row
    # without a label.  Ordered FIRST: a safety condition outranks any
    # provider intent.
    refusal = _refusal_intent(low, text, merged, tool_summary_error)
    if refusal is not None:
        render_intent = refusal

    # ── routing decision tree (live planner v67 order) ────────────────────
    elif wants_reference:
        # Resolve from thread_context; never re-search, never invent an entity.
        render_intent = {"kind": "summarize"}
    elif merged.get("trip_confirmed"):
        render_intent = {"kind": "trip_map"}
    elif view_order_now and merged.get("order_id"):
        render_intent = {"kind": "order_detail"}
    elif wants_transfers and region:
        tool_requests = [
            {
                "tool": TOOL_HOTELBEDS_TRANSFERS,
                "arguments": {
                    "from_type": "IATA",
                    "from_code": city_code,
                    "to_type": "ATLAS",
                    "outbound": merged.get("check_in_date"),
                    "adults": adults,
                },
            }
        ]
        render_intent = {"kind": "show_transfers"}
    elif wants_hotel and region:
        tool_requests = [
            {
                "tool": TOOL_HOTELBEDS_HOTELS,
                # Argument names follow the HotelBeds provider inputSchema
                # (automation/agents/mcp/hotelbeds search_hotels): snake_case
                # check_in/check_out and a city hint, not the retired Amadeus
                # cityCode/checkInDate shape.
                "arguments": {
                    "city": region.get("label", ""),
                    "city_code": city_code,
                    "check_in": merged.get("check_in_date"),
                    "check_out": merged.get("check_out_date"),
                    "adults": adults,
                    "rooms": party.get("rooms", 1),
                    "children": len(party.get("children") or []),
                    "radius": 20,
                },
            }
        ]
        render_intent = {"kind": "show_hotels"}
    # POI discovery resolves through Google Places, not the bookable-activity
    # provider.  Checked BEFORE wants_activities so "book a food tour" (a
    # bookable item) still routes to HotelBeds Activities.
    elif wants_poi and not wants_activities and region:
        tool_requests = [
            {
                "tool": TOOL_GOOGLE_PLACES,
                "arguments": {"query": text or region.get("label", ""),
                              "max_results": 8},
            }
        ]
        render_intent = {"kind": "show_places"}
    elif wants_activities and region:
        tool_requests = [
            {
                "tool": TOOL_HOTELBEDS_ACTIVITIES,
                "arguments": {
                    "destination": city_code,
                    "from": merged.get("check_in_date"),
                    "to": merged.get("check_out_date"),
                    "language": "en",
                    "adults": adults,
                },
            }
        ]
        render_intent = {"kind": "show_activities"}
    elif wants_flight and region:
        tool_requests = [
            {
                "tool": TOOL_DUFFEL_OFFERS,
                "arguments": {
                    "origin": DEFAULT_ORIGIN,
                    "destination": city_code,
                    "departure_date": merged.get("check_in_date"),
                    "adults": adults,
                    "cabin_class": "economy",
                },
            }
        ]
        render_intent = {"kind": "show_flights"}
    elif merged.get("picked_hotel_id") and (
        merged.get("picked_hotel_rate_key")
        or any(w in low for w in ("select this room", "continue to book",
                                  "select room"))
    ) and not wants_order:
        render_intent = {"kind": "hotel_confirmation"}
    elif merged.get("picked_hotel_id") and wants_order:
        tool_requests = [
            {
                "tool": TOOL_HOTELBEDS_BOOK,
                "arguments": {
                    "rate_key": merged.get("picked_hotel_rate_key", ""),
                    "holder_name": "Alex",
                    "holder_surname": "Traveller",
                    "adults": adults,
                },
            }
        ]
        render_intent = {"kind": "hotel_confirmation"}
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
    elif view_order_now and merged.get("order_id"):
        render_intent = {"kind": "order_detail"}
    elif merged.get("picked_flight_offer_id") and view_flight_now:
        render_intent = {"kind": "flight_detail"}
    elif wants_calendar:
        render_intent = {"kind": "calendar_live"}
    elif wants_map and merged.get("places_seen"):
        render_intent = {"kind": "trip_map"}
    # A comparison with an active hotel list is a HOTEL comparison (E3 renders
    # hotel_compare), not a destination trade-off — so it falls through to the
    # hotel-refinement branch below.  Only a comparison with no result set in
    # context is the H5 "iceland vs morocco" narration.
    elif wants_compare and not merged.get("hotel_search_results"):
        render_intent = {"kind": "summarize"}
    elif wants_summary and (
        region
        or merged.get("picked_flight_offer_id")
        or merged.get("picked_hotel_id")
        or merged.get("flight_search_results")
        or merged.get("hotel_search_results")
    ):
        render_intent = {"kind": "summary"}
    # Refining an ACTIVE hotel result set.  E2/E3/E4 phrase the refinement
    # without repeating the word "hotel" ("with breakfast and wifi",
    # "4 stars and up"), so keyword detection alone routes them to the generic
    # flight branch.  A hotel list already in context is the disambiguator.
    elif merged.get("hotel_search_results") and any(
        w in low for w in
        ("breakfast", "wifi", "pool", "spa", "pet", "star", "stars", "rating",
         "reviewed", "review", "value", "compare", "side by side", "board",
         "family room", "refundable")
    ):
        render_intent = {"kind": "show_hotels"}
    # An explicit correction that invalidates the active search: re-run it
    # rather than fall through to `summarize`.
    elif wants_research and merged.get("flight_search_results") and not region_restated:
        tool_requests = [
            {
                "tool": TOOL_DUFFEL_OFFERS,
                "arguments": {
                    "origin": DEFAULT_ORIGIN,
                    "destination": city_code,
                    "departure_date": merged.get("check_in_date"),
                    "adults": adults,
                    "cabin_class": "economy",
                },
            }
        ]
        render_intent = {"kind": "show_flights"}
    elif wants_poi and not region:
        tool_requests = [
            {
                "tool": TOOL_GOOGLE_PLACES,
                "arguments": {"query": text, "max_results": 8},
            }
        ]
        render_intent = {"kind": "show_places"}
    # Place resolution runs BEFORE the completeness gate: a named region with
    # no resolved places is a show_places turn even when dates/party are absent.
    # `region_restated` re-opens it: a swapped destination invalidates the
    # previously resolved places.
    elif region and (not merged.get("places_seen") or region_restated):
        tool_requests = [
            {
                "tool": TOOL_GOOGLE_PLACES,
                "arguments": {"query": region.get("label", ""), "max_results": 5},
            }
        ]
        render_intent = {"kind": "show_places"}
    elif _ready(merged) and not merged.get("flight_search_results"):
        tool_requests = [
            {
                "tool": TOOL_DUFFEL_OFFERS,
                "arguments": {
                    "origin": DEFAULT_ORIGIN,
                    "destination": city_code,
                    "departure_date": merged.get("check_in_date"),
                    "adults": adults,
                    "cabin_class": "economy",
                },
            }
        ]
        render_intent = {"kind": "show_flights"}
    elif not _ready(merged):
        # FALLBACK, not the first gate — see the note at the top of this block.
        render_intent = {"kind": "collect_missing", "missing": _missing(merged)}
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
    # A teacher (or any non-oracle label source) may emit a tool request whose
    # routing key drifted from the contract (``tool_id`` / ``tool_name`` instead
    # of ``tool``).  Read defensively so a missing ``tool`` key never crashes the
    # whole batch — an unroutable request degrades to an empty summary, not a
    # KeyError (noetl/ai-meta#140 Phase 1: the prior ceiling run aborted every
    # such turn with ``KeyError: 'tool'``).
    first = reqs[0] if isinstance(reqs[0], dict) else {}
    tool = first.get("tool") or first.get("tool_id") or first.get("tool_name") or ""
    region = slot_state.get("region") or {}
    if tool == TOOL_GOOGLE_PLACES:
        return {"ok": True, "tool": tool, "data": {"places": _fixture_places(region)}}
    if tool == TOOL_DUFFEL_OFFERS:
        return {
            "ok": True,
            "tool": tool,
            "data": {"offers": _fixture_flights(region, slot_state.get("check_in_date", "2026-07-10"))},
        }
    if tool == TOOL_HOTELBEDS_HOTELS:
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
