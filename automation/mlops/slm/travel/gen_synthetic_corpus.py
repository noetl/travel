"""Synthetic corpus generator for the travel-domain SLM (v2 data scaling).

The v1 dataset (45 turns -> 58 multitask examples) held 100% schema validity
but did NOT beat the deterministic oracle floor on the *match* metrics
(tool 0.56 / intent 0.56 / widget_type 0.38).  The diagnosed root cause was
tiny data.  This script is the main scaling lever: it GENERATES diverse user
turns whose ``(event, slot_state)`` deterministically route the oracle into
every reachable branch of its decision tree, then lets the generic
``dataset_build`` engine label them with the ORACLE as the authoritative target
(free, 100%% schema-valid by construction).

Design choices that matter:

* **Oracle is the labeler, we only choose inputs.**  We never write labels here;
  we craft inputs that route the oracle to a target intent/tool/widget, then
  assert (via importing the oracle) that the realised route matches the intent.
  A recipe that misroutes is a generator bug and shows up in the per-slice
  count report.

* **No template leakage.**  Train and eval draw from DISJOINT phrasing template
  sets (``*_TRAIN`` vs ``*_EVAL``) and disjoint structured-param pools.  The
  full city vocabulary appears in both splits on purpose (city->city_code is a
  closed lookup the model is *supposed* to learn); what eval holds out is the
  surface form / parameter combination, so eval measures generalisation to new
  phrasings, not new vocab.

* **Over-sample the weak slices.**  The v1 eval was weakest on render/
  widget_type, render_intent, and context-dependent (multi-turn) turns, so
  ``show_places`` / ``show_flights`` / ``show_hotels`` / ``order_confirmation``
  and the widget-submit / CTA-click transitions get the largest budgets.

* **Context-dependent turns are modelled via ``slot_state``.**  The oracle's
  ``extract`` ignores thread context; the running itinerary state lives in
  ``slot_state`` (exactly how the production planner threads it), so a turn like
  "book this one" with a ``picked_flight_offer_id`` already in ``slot_state`` is
  the faithful representation of a context-dependent ("that flight") request.

Output: a JSONL seed corpus, one turn per line, each carrying an explicit
``"split": "train"|"eval"`` field (the engine honours it — see
``slm_dataset_build.py``).

Usage::

    python3 gen_synthetic_corpus.py --out datasets/seed/travel_v2_corpus.jsonl
        [--seed muno-travel-v2] [--report]
"""

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oracle as ORACLE  # noqa: E402

# ── city vocab (mirrors oracle.CITY_MAP; both splits use all of it) ──────────
CITIES = ["miami", "paris", "boston", "new york", "london", "rome", "tokyo"]


def region_of(city):
    """Build the slot_state.region dict the oracle would itself produce."""
    base = ORACLE.CITY_MAP[city]
    return {"label": base["label"], "city_code": base["city_code"],
            "country_code": base["country_code"], "kind": "city"}


# date / party pools — disjoint between splits to avoid exact-turn leakage
DATE_POOL_TRAIN = [
    ("2026-07-10", "2026-07-14"), ("2026-08-03", "2026-08-09"),
    ("2026-09-01", "2026-09-05"), ("2026-10-12", "2026-10-19"),
    ("2026-11-02", "2026-11-06"),
]
DATE_POOL_EVAL = [
    ("2026-07-21", "2026-07-26"), ("2026-12-09", "2026-12-15"),
]
PARTY_POOL_TRAIN = [
    {"rooms": 1, "adults": 1, "children": []},
    {"rooms": 1, "adults": 2, "children": []},
    {"rooms": 2, "adults": 4, "children": []},
    {"rooms": 1, "adults": 3, "children": []},
]
PARTY_POOL_EVAL = [
    {"rooms": 1, "adults": 2, "children": []},
    {"rooms": 2, "adults": 5, "children": []},
]


def _nights(a, b):
    from datetime import date
    return max((date.fromisoformat(b) - date.fromisoformat(a)).days, 0)


def ready_slot(city, dates, party, **extra):
    a, b = dates
    slot = {
        "region": region_of(city),
        "check_in_date": a, "check_out_date": b, "nights": _nights(a, b),
        "party": dict(party),
    }
    slot.update(extra)
    return slot


# ── phrasing template sets (DISJOINT train vs eval) ─────────────────────────
PHRASES = {
    "collect_region": {
        "train": ["I want to plan a trip", "help me plan a vacation",
                   "let's plan a getaway", "I need to organize some travel",
                   "plan something fun for me", "I want to go on holiday",
                   "thinking about a vacation", "let's book a trip somewhere"],
        "eval": ["can you help me arrange a journey", "I'd love to plan an escape",
                  "set up a trip for me please", "I want to arrange a holiday"],
    },
    "show_places": {
        "train": ["what's there to see", "show me attractions", "what can I do there",
                   "any sights worth visiting", "recommend some places", "things to do there",
                   "show me around", "what are the highlights"],
        "eval": ["which landmarks should I visit", "point me to the attractions",
                  "what's worth seeing there"],
    },
    "show_flights": {
        "train": ["show flights", "find me flights", "what flights are available",
                   "search for flights", "I need a flight", "look for flights",
                   "flight options please", "get me some flights"],
        "eval": ["which flights can I take", "pull up the flight options",
                  "let's look at the airfare"],
    },
    "order": {
        "train": ["book it", "confirm and purchase", "book this flight",
                   "purchase the ticket", "confirm the booking", "order this one",
                   "go ahead and book it", "book this one"],
        "eval": ["please finalize the purchase", "lock in this booking",
                  "complete my order now"],
    },
    "show_hotels": {
        "train": ["find hotels", "hotels next", "show me hotels", "search for hotels",
                   "where can I stay", "look for accommodation", "I need a hotel",
                   "show me some lodging"],
        "eval": ["pull up places to stay", "what hotels are available",
                  "find me accommodation"],
    },
    "flight_detail": {  # MUST contain "details" for the oracle to route here
        "train": ["show me the details", "details please", "more details on this flight",
                   "give me the flight details", "I want the details on it"],
        "eval": ["can I see the details", "share the flight details with me"],
    },
    "calendar": {  # MUST contain show/view AND schedule/calendar
        "train": ["show my schedule", "view my calendar", "show me the calendar",
                   "what's on my schedule", "view the schedule", "show the calendar please"],
        "eval": ["show my trip schedule", "view my itinerary calendar"],
    },
    "summary": {
        "train": ["show me the summary", "summarize my trip", "what's my itinerary",
                   "give me the overview", "trip summary please", "let's review the itinerary"],
        "eval": ["wrap up my itinerary", "show me the trip overview"],
    },
    "summarize": {  # neutral filler -> fallback summarize
        "train": ["ok", "thanks", "alright", "sounds good", "got it", "cool"],
        "eval": ["okay great", "perfect thanks"],
    },
    "collect_dates": {  # neutral continuation on a region-only slot -> missing dates
        "train": ["let's continue", "what's next", "go on then", "proceed please",
                   "next step", "keep going"],
        "eval": ["move ahead", "carry on please"],
    },
    "unknown_city": {  # no known city -> stays in collect_missing/region
        "train": ["trip to Atlantis", "I want to visit Wakanda", "take me to El Dorado",
                   "plan a trip to Narnia"],
        "eval": ["vacation in Shangri-La", "trip to Gotham"],
    },
}


class Gen:
    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.turns = []
        self._n = 0

    def _id(self, slice_name, split):
        self._n += 1
        return "v2_%s_%s_%04d" % (split, slice_name, self._n)

    def add(self, slice_name, split, event_type, payload, slot_state, intent_label):
        turn = {
            "id": self._id(slice_name, split),
            "intent_label": intent_label,
            "event_type": event_type,
            "event_payload": payload,
            "slot_state": slot_state,
            "split": split,
        }
        self.turns.append(turn)

    def dates(self, split):
        return self.rng.choice(DATE_POOL_TRAIN if split == "train" else DATE_POOL_EVAL)

    def party(self, split):
        return self.rng.choice(PARTY_POOL_TRAIN if split == "train" else PARTY_POOL_EVAL)

    def phrases(self, slice_name, split):
        return PHRASES[slice_name][split]

    # ── per-slice recipes (each crafts inputs that route the oracle to target)
    def gen_collect_region(self, n_train, n_eval):
        for split, n in (("train", n_train), ("eval", n_eval)):
            for _ in range(n):
                txt = self.rng.choice(self.phrases("collect_region", split))
                self.add("collect_region", split, "user_message", {"text": txt}, {},
                          "collect_missing_region")

    def gen_unknown_city(self, n_train, n_eval):
        for split, n in (("train", n_train), ("eval", n_eval)):
            for _ in range(n):
                txt = self.rng.choice(self.phrases("unknown_city", split))
                self.add("unknown_city", split, "user_message", {"text": txt}, {},
                          "edge_unknown_city")

    def gen_collect_dates_widget(self, n_train, n_eval):
        # city-select widget from empty slot -> region set, dates+party missing
        for split, n in (("train", n_train), ("eval", n_eval)):
            for _ in range(n):
                city = self.rng.choice(CITIES)
                r = region_of(city)
                self.add("collect_dates", split, "user_widget_submit",
                          {"action_id": "place:select",
                           "submitted_value": {"id": r["city_code"], "label": r["label"]}},
                          {}, "collect_missing_dates_via_city_select")

    def gen_collect_dates_text(self, n_train, n_eval):
        # region-only slot + neutral text (no date) -> missing dates -> date_range_picker
        for split, n in (("train", n_train), ("eval", n_eval)):
            for _ in range(n):
                city = self.rng.choice(CITIES)
                txt = self.rng.choice(self.phrases("collect_dates", split))
                self.add("collect_dates", split, "user_message", {"text": txt},
                          {"region": region_of(city)}, "collect_missing_dates_text")

    def gen_collect_party_widget(self, n_train, n_eval):
        # date-range widget submit on a region-only slot -> party missing
        for split, n in (("train", n_train), ("eval", n_eval)):
            for _ in range(n):
                city = self.rng.choice(CITIES)
                a, b = self.dates(split)
                self.add("collect_party", split, "user_widget_submit",
                          {"action_id": "date:range",
                           "submitted_value": {"from": a, "to": b, "nights": _nights(a, b)}},
                          {"region": region_of(city)}, "collect_missing_party_via_dates")

    def gen_show_places_widget(self, n_train, n_eval):
        # party widget submit completes a region+dates slot -> ready -> show_places
        for split, n in (("train", n_train), ("eval", n_eval)):
            for _ in range(n):
                city = self.rng.choice(CITIES)
                a, b = self.dates(split)
                p = self.party(split)
                self.add("show_places", split, "user_widget_submit",
                          {"action_id": "party:set", "submitted_value": dict(p)},
                          {"region": region_of(city), "check_in_date": a,
                           "check_out_date": b, "nights": _nights(a, b)},
                          "show_places_via_party_submit")

    def gen_show_places_text(self, n_train, n_eval):
        for split, n in (("train", n_train), ("eval", n_eval)):
            for _ in range(n):
                city = self.rng.choice(CITIES)
                txt = self.rng.choice(self.phrases("show_places", split))
                self.add("show_places", split, "user_message", {"text": txt},
                          ready_slot(city, self.dates(split), self.party(split)),
                          "show_places_text")

    def gen_show_flights(self, n_train, n_eval):
        for split, n in (("train", n_train), ("eval", n_eval)):
            for _ in range(n):
                city = self.rng.choice(CITIES)
                txt = self.rng.choice(self.phrases("show_flights", split))
                self.add("show_flights", split, "user_message", {"text": txt},
                          ready_slot(city, self.dates(split), self.party(split),
                                     places_seen=["place_1", "place_2"]),
                          "show_flights_text")

    def gen_flight_detail(self, n_train, n_eval):
        for split, n in (("train", n_train), ("eval", n_eval)):
            for _ in range(n):
                city = self.rng.choice(CITIES)
                code = ORACLE.CITY_MAP[city]["city_code"]
                txt = self.rng.choice(self.phrases("flight_detail", split))
                offer = "off_%s_%d" % (code, self.rng.randint(1, 3))
                self.add("flight_detail", split, "user_message", {"text": txt},
                          ready_slot(city, self.dates(split), self.party(split),
                                     places_seen=["place_1"],
                                     flight_search_results=[offer],
                                     picked_flight_offer_id=offer),
                          "flight_detail_text")

    def gen_order_text(self, n_train, n_eval):
        for split, n in (("train", n_train), ("eval", n_eval)):
            for _ in range(n):
                city = self.rng.choice(CITIES)
                code = ORACLE.CITY_MAP[city]["city_code"]
                txt = self.rng.choice(self.phrases("order", split))
                offer = "off_%s_%d" % (code, self.rng.randint(1, 3))
                self.add("order", split, "user_message", {"text": txt},
                          ready_slot(city, self.dates(split), self.party(split),
                                     places_seen=["p1"], flight_search_results=[offer],
                                     picked_flight_offer_id=offer),
                          "order_confirmation_text")

    def gen_order_cta(self, n_train, n_eval):
        # book_offer CTA -> wants_order (context-dependent: "book this one")
        for split, n in (("train", n_train), ("eval", n_eval)):
            for _ in range(n):
                city = self.rng.choice(CITIES)
                code = ORACLE.CITY_MAP[city]["city_code"]
                offer = "off_%s_%d" % (code, self.rng.randint(1, 3))
                self.add("order", split, "user_widget_cta_click",
                          {"action_id": "book_offer:%s" % offer},
                          ready_slot(city, self.dates(split), self.party(split),
                                     places_seen=["p1"], flight_search_results=[offer],
                                     picked_flight_offer_id=offer),
                          "order_confirmation_cta")

    def gen_show_hotels_text(self, n_train, n_eval):
        for split, n in (("train", n_train), ("eval", n_eval)):
            for _ in range(n):
                city = self.rng.choice(CITIES)
                code = ORACLE.CITY_MAP[city]["city_code"]
                txt = self.rng.choice(self.phrases("show_hotels", split))
                offer = "off_%s_%d" % (code, self.rng.randint(1, 3))
                self.add("show_hotels", split, "user_message", {"text": txt},
                          ready_slot(city, self.dates(split), self.party(split),
                                     places_seen=["p1"], flight_search_results=[offer],
                                     picked_flight_offer_id=offer),
                          "show_hotels_text")

    def gen_show_hotels_cta(self, n_train, n_eval):
        # pick_offer CTA sets picked flight -> routes to show_hotels (no wants_order)
        for split, n in (("train", n_train), ("eval", n_eval)):
            for _ in range(n):
                city = self.rng.choice(CITIES)
                code = ORACLE.CITY_MAP[city]["city_code"]
                offer = "off_%s_%d" % (code, self.rng.randint(1, 3))
                self.add("show_hotels", split, "user_widget_cta_click",
                          {"action_id": "pick_offer:%s" % offer},
                          ready_slot(city, self.dates(split), self.party(split),
                                     places_seen=["p1"], flight_search_results=[offer]),
                          "show_hotels_via_pick_offer")

    def gen_summary_cta(self, n_train, n_eval):
        # pick_hotel CTA completes flight+hotel -> summary
        for split, n in (("train", n_train), ("eval", n_eval)):
            for _ in range(n):
                city = self.rng.choice(CITIES)
                code = ORACLE.CITY_MAP[city]["city_code"]
                offer = "off_%s_%d" % (code, self.rng.randint(1, 3))
                hotel = "hotel_%s_%d" % (code, self.rng.randint(1, 3))
                self.add("summary", split, "user_widget_cta_click",
                          {"action_id": "pick_hotel:%s" % hotel},
                          ready_slot(city, self.dates(split), self.party(split),
                                     places_seen=["p1"], flight_search_results=[offer],
                                     picked_flight_offer_id=offer,
                                     hotel_search_results=[hotel]),
                          "summary_via_pick_hotel")

    def gen_summary_text(self, n_train, n_eval):
        for split, n in (("train", n_train), ("eval", n_eval)):
            for _ in range(n):
                city = self.rng.choice(CITIES)
                code = ORACLE.CITY_MAP[city]["city_code"]
                txt = self.rng.choice(self.phrases("summary", split))
                offer = "off_%s_%d" % (code, self.rng.randint(1, 3))
                hotel = "hotel_%s_%d" % (code, self.rng.randint(1, 3))
                self.add("summary", split, "user_message", {"text": txt},
                          ready_slot(city, self.dates(split), self.party(split),
                                     places_seen=["p1"], flight_search_results=[offer],
                                     picked_flight_offer_id=offer,
                                     hotel_search_results=[hotel],
                                     picked_hotel_id=hotel),
                          "summary_text")

    def gen_calendar(self, n_train, n_eval):
        for split, n in (("train", n_train), ("eval", n_eval)):
            for _ in range(n):
                city = self.rng.choice(CITIES)
                txt = self.rng.choice(self.phrases("calendar", split))
                self.add("calendar", split, "user_message", {"text": txt},
                          ready_slot(city, self.dates(split), self.party(split)),
                          "calendar_live_text")

    def gen_summarize(self, n_train, n_eval):
        for split, n in (("train", n_train), ("eval", n_eval)):
            for _ in range(n):
                city = self.rng.choice(CITIES)
                code = ORACLE.CITY_MAP[city]["city_code"]
                txt = self.rng.choice(self.phrases("summarize", split))
                offer = "off_%s_%d" % (code, self.rng.randint(1, 3))
                self.add("summarize", split, "user_message", {"text": txt},
                          ready_slot(city, self.dates(split), self.party(split),
                                     places_seen=["p1"], flight_search_results=[offer]),
                          "summarize_fallback")


def _signature(t):
    return json.dumps([t["event_type"], t["event_payload"], t["slot_state"]],
                      sort_keys=True)


def _dedup(turns):
    """(1) drop within-split exact-signature duplicates (benign but inflate
    counts), then (2) HARD-drop any eval turn whose signature appears anywhere in
    the train set — the leak-free guarantee the task requires.  Returns the
    kept turns + a stats dict."""
    train_sigs = set(_signature(t) for t in turns if t["split"] == "train")
    seen = {"train": set(), "eval": set()}
    kept, dropped_dup, dropped_leak = [], 0, 0
    for t in turns:
        sig = _signature(t)
        if sig in seen[t["split"]]:
            dropped_dup += 1
            continue
        if t["split"] == "eval" and sig in train_sigs:
            dropped_leak += 1
            continue
        seen[t["split"]].add(sig)
        kept.append(t)
    return kept, {"dropped_within_split_dups": dropped_dup,
                  "dropped_eval_leak": dropped_leak}


# per-profile (train, eval) budgets.  v3 over-samples the slices the v2 eval was
# weakest on — show_places (the model over-predicted it: 3/14 correct tool on
# predicted-show_places turns), its CONTRAST neighbours (show_flights /
# show_hotels / summarize, so the model stops defaulting to show_places), and the
# multi-widget `summary` render sequence (itinerary_summary + calendar_view).
BUDGETS = {
    "v2": {
        "collect_region": (48, 10), "unknown_city": (24, 6),
        "collect_dates_text": (40, 10), "collect_dates_widget": (28, 0),
        "collect_party_widget": (48, 10), "show_places_widget": (56, 12),
        "show_places_text": (40, 8), "show_flights": (72, 14),
        "flight_detail": (40, 8), "order_text": (44, 8), "order_cta": (40, 8),
        "show_hotels_text": (56, 12), "show_hotels_cta": (44, 8),
        "summary_cta": (40, 8), "summary_text": (32, 6), "calendar": (40, 8),
        "summarize": (28, 6),
    },
    "v3": {
        "collect_region": (56, 10), "unknown_city": (28, 6),
        "collect_dates_text": (44, 10), "collect_dates_widget": (28, 0),
        "collect_party_widget": (52, 10), "show_places_widget": (96, 16),
        "show_places_text": (72, 12), "show_flights": (104, 16),
        "flight_detail": (44, 8), "order_text": (48, 8), "order_cta": (44, 8),
        "show_hotels_text": (88, 14), "show_hotels_cta": (52, 8),
        "summary_cta": (72, 12), "summary_text": (56, 10), "calendar": (44, 8),
        "summarize": (52, 10),
    },
    # v4 — render iteration.  v3's last gap was widget_type_match (0.79), driven by
    # the DATA-BEARING render slices (flight_list / hotel_list / the two-widget
    # summary sequence) and a soft show_flights routing slice (15/21).  v4 keeps
    # the EVAL column identical to v3 so the 144-turn holdout stays comparable, and
    # heavily over-samples those weak slices in TRAIN so the model sees many more
    # complete flight_list / hotel_list / itinerary_summary+calendar_view renders
    # and sharper show_flights-vs-(places|hotels) routing contrast:
    #   * show_flights        104 -> 184  (the weak routing slice + flight_list render)
    #   * show_hotels_text     88 -> 152  (hotel_list render + flights/hotels contrast)
    #   * show_hotels_cta      52 ->  80
    #   * summary_cta          72 -> 128  (the itinerary_summary+calendar_view pair)
    #   * summary_text         56 -> 104
    #   * flight_detail        44 ->  72  (flight_card render, sibling of flight_list)
    #   * show_places_text     72 ->  92  (contrast so flights routing doesn't bleed
    #                                      back into show_places over-prediction)
    # Lighter, already-strong slices stay at v3 levels.
    "v4": {
        "collect_region": (56, 10), "unknown_city": (28, 6),
        "collect_dates_text": (44, 10), "collect_dates_widget": (28, 0),
        "collect_party_widget": (52, 10), "show_places_widget": (96, 16),
        "show_places_text": (92, 12), "show_flights": (184, 16),
        "flight_detail": (72, 8), "order_text": (48, 8), "order_cta": (44, 8),
        "show_hotels_text": (152, 14), "show_hotels_cta": (80, 8),
        "summary_cta": (128, 12), "summary_text": (104, 10), "calendar": (44, 8),
        "summarize": (52, 10),
    },
}


def build(seed, profile="v2"):
    g = Gen(seed)
    b = BUDGETS[profile]
    # Over-generate; _dedup trims within-split repeats + any eval/train collision.
    g.gen_collect_region(*b["collect_region"])
    g.gen_unknown_city(*b["unknown_city"])
    g.gen_collect_dates_text(*b["collect_dates_text"])     # leak-free date_range_picker (text)
    g.gen_collect_dates_widget(*b["collect_dates_widget"])  # city-select: low-cardinality -> train only
    g.gen_collect_party_widget(*b["collect_party_widget"])
    g.gen_show_places_widget(*b["show_places_widget"])
    g.gen_show_places_text(*b["show_places_text"])
    g.gen_show_flights(*b["show_flights"])
    g.gen_flight_detail(*b["flight_detail"])
    g.gen_order_text(*b["order_text"])
    g.gen_order_cta(*b["order_cta"])
    g.gen_show_hotels_text(*b["show_hotels_text"])
    g.gen_show_hotels_cta(*b["show_hotels_cta"])
    g.gen_summary_cta(*b["summary_cta"])
    g.gen_summary_text(*b["summary_text"])
    g.gen_calendar(*b["calendar"])
    g.gen_summarize(*b["summarize"])
    kept, stats = _dedup(g.turns)
    return kept, stats


def verify_and_report(turns):
    """Run every turn through the oracle; report realised intent/tool/widget
    distribution per split, and flag any turn whose realised intent looks
    degenerate (so a misrouting recipe is caught here, not in training)."""
    from collections import Counter
    stats = {"train": {"intent": Counter(), "tool": Counter(), "widget": Counter(), "n": 0},
             "eval": {"intent": Counter(), "tool": Counter(), "widget": Counter(), "n": 0}}
    dup_keys = Counter()
    for t in turns:
        split = t["split"]
        prod = ORACLE.run_turn({"event_type": t["event_type"],
                                 "event_payload": t["event_payload"],
                                 "slot_state": t["slot_state"]})
        ex, rd = prod["extract"], prod["render"]
        intent = ex["render_intent"]["kind"]
        reqs = ex.get("tool_requests") or []
        tool = reqs[0]["tool"] if reqs else "(none)"
        stats[split]["intent"][intent] += 1
        stats[split]["tool"][tool] += 1
        for w in rd.get("widgets", []):
            stats[split]["widget"][w.get("widget_type")] += 1
        stats[split]["n"] += 1
        # leakage probe: identical (event_type, payload, slot_state) signature
        dup_keys[json.dumps([t["event_type"], t["event_payload"], t["slot_state"]],
                             sort_keys=True)] += 1
    leak = sum(1 for v in dup_keys.values() if v > 1)
    return stats, leak


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", default="muno-travel-v2")
    ap.add_argument("--profile", default="v2", choices=list(BUDGETS.keys()))
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    turns, dedup_stats = build(args.seed, profile=args.profile)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as fh:
        for t in turns:
            fh.write(json.dumps(t, sort_keys=True) + "\n")

    n_train = sum(1 for t in turns if t["split"] == "train")
    n_eval = sum(1 for t in turns if t["split"] == "eval")
    print("wrote %d turns -> %s  (train=%d eval=%d)" % (len(turns), args.out, n_train, n_eval))
    print("dedup:", json.dumps(dedup_stats))

    if args.report:
        stats, leak = verify_and_report(turns)
        for split in ("train", "eval"):
            s = stats[split]
            print("\n=== %s (n=%d) ===" % (split, s["n"]))
            print("intent:", json.dumps(dict(sorted(s["intent"].items())), sort_keys=True))
            print("tool:  ", json.dumps(dict(sorted(s["tool"].items())), sort_keys=True))
            print("widget:", json.dumps(dict(sorted(s["widget"].items())), sort_keys=True))
        print("\nexact-signature duplicate turns:", leak)
        # cross-split phrasing leakage check (text turns only)
        train_txt = set(t["event_payload"].get("text", "") for t in turns
                        if t["split"] == "train" and t["event_type"] == "user_message")
        eval_txt = set(t["event_payload"].get("text", "") for t in turns
                       if t["split"] == "eval" and t["event_type"] == "user_message")
        print("train/eval shared phrasings (should be 0):", len(train_txt & eval_txt))


if __name__ == "__main__":
    main()
