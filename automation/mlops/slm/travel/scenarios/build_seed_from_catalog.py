#!/usr/bin/env python3
"""Expand the scenario catalog into seed turn rows.

Input : scenarios/use_cases_catalog.md — the product-owned scenario catalog
        (groups A-O), which is the source of truth for the corpus.
Output: datasets/seed/travel_catalog_turns.jsonl — one row per
        (scenario x user_prompt phrasing), in the SAME per-turn schema the
        existing travel_seed_turns.jsonl uses, so oracle.run_turn() fans each
        row out to the extract and render roles unchanged.

Why per-turn and not per-role: the Product Owner playbook §5 describes "one
row per prompt phrasing x role", but that is the *expanded* form.  The
installed pipeline seeds turns and derives both role labels from the oracle,
so emitting per-role rows here would fork the pipeline.

Roadmap rows (tools not in the live planner) are emitted but carry
eval_split="roadmap" and MUST be excluded from train/eval — the promotion
check "tool exists in live planner" would correctly fail on them.

Usage:
    python3 scenarios/build_seed_from_catalog.py [--check]

    --check  parse and report coverage only; write nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CATALOG = os.path.join(HERE, "use_cases_catalog.md")
OUT = os.path.join(ROOT, "datasets", "seed", "travel_catalog_turns.jsonl")

# Groups whose tools are not in the live planner vocabulary.  L1 is retrieval
# and stays live; L2-L6 are roadmap.  Recorded here rather than inferred so a
# future promotion is a one-line edit (PO playbook §6 step 4).
ROADMAP_GROUPS = {"M", "N", "O"}
ROADMAP_CELLS = {"L2", "L3", "L4", "L5", "L6"}

# Widget-driven cells carry a typed action payload, not free text.  The first
# build emitted `action_id: <scenario_id>` ("cta.flight.select"), which is not
# an id the planner ever emits -- so those rows exercised nothing.  These are
# the real action ids from the widget contract.
WIDGET_ACTIONS = {
    "K1":  {"action_id": "pick_place:paris"},
    "K2":  {"action_id": "date:submit", "from": "2026-09-10", "to": "2026-09-14"},
    "K3":  {"action_id": "party:submit", "adults": 2, "children": []},
    "K4":  {"action_id": "filter:apply", "board": "BB", "amenities": ["wifi"]},
    "K5":  {"action_id": "view_offer:off_fixture_0001"},
    "K6":  {"action_id": "book_offer:off_fixture_0001"},
    "K7":  {"action_id": "pick_hotel:hot_fixture_0001"},
    "K8":  {"action_id": "book_hotel:hot_fixture_0001", "rate_key": "rk_fixture"},
    "K9":  {"action_id": "book_activity:act_fixture_0001"},
    "K10": {"action_id": "view_map"},
    "D6":  {"action_id": "book_offer:off_fixture_0001"},
    "E5":  {"action_id": "pick_hotel:hot_fixture_0001", "rate_key": "rk_fixture"},
    "E6":  {"action_id": "book_hotel:hot_fixture_0001", "rate_key": "rk_fixture"},
    "F4":  {"action_id": "book_activity:act_fixture_0001"},
    "G3":  {"action_id": "book_transfer:xf_fixture_0001"},
    "H2":  {"action_id": "view_calendar"},
    "H3":  {"action_id": "view_map"},
}

# Cells whose precondition IS a failed/empty provider response.
PROVIDER_ERROR_CELLS = {"J4", "G5"}

SEP = "·"  # the '·' the catalog uses between inline fields

FIELD_KEYS = (
    "coverage_id", "intent", "event_type", "eval_split", "user_prompts",
    "preconditions", "slots_to_fill", "expected_extract", "expected_render",
    "negative_constraints", "follow_up_question", "output_widget",
    "proposed tool", "proposed tools", "proposed chain", "render_intent",
)


# Word symbol-font glyphs survive the .docx -> text conversion as Unicode
# private-use-area codepoints (e.g. U+EC02 in front of 18 of the 72 scenario
# headings).  They are invisible in most viewers, so a heading regex that does
# not strip them silently drops those scenarios — which is how a first pass
# reported 64 of 82 with every gate PASSing.
_PUA = re.compile("[\uE000-\uF8FF]")


def _clean(line: str) -> str:
    return _PUA.sub("", line)


def _split_inline(line: str) -> list[str]:
    """Split a bullet line on the catalog's '·' separator."""
    return [p.strip() for p in line.split(SEP) if p.strip()]


def _kv(chunk: str):
    m = re.match(r"^\**([a-z_ ]+)\**\s*:\s*(.*)$", chunk.strip(), re.I)
    if not m:
        return None, None
    key = m.group(1).strip().lower()
    return (key, m.group(2).strip()) if key in FIELD_KEYS else (None, None)


def parse_prompts(raw: str) -> list[str]:
    """`"a"; "b"; "c" …` -> ['a','b','c'].

    Quoted spans are the reliable signal; the catalog decorates the field with
    parentheticals ('(CTA)', '(3-10)', '(same as G1 but ...)') that are notes,
    not phrasings, so only quoted runs are taken.
    """
    out, seen = [], set()
    for m in re.finditer(r'"([^"]+)"', raw):
        p = m.group(1).strip()
        # drop ellipsis placeholders and empty spans
        if not p or p in {"…", "..."}:
            continue
        if p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out


def parse_catalog(text: str) -> list[dict]:
    lines = [_clean(l) for l in text.split("\n")]
    scenarios: list[dict] = []
    cur: dict | None = None

    head_re = re.compile(r"^###\s+([A-O]\d+)\s*" + SEP + r"\s*(\S+)")
    for raw in lines:
        h = head_re.match(raw)
        if h:
            if cur:
                scenarios.append(cur)
            cur = {
                "coverage_id": h.group(1),
                "scenario_id": h.group(2).strip(),
                "fields": {},
            }
            continue
        if cur is None:
            continue
        if raw.startswith("### ") or raw.startswith("## "):
            scenarios.append(cur)
            cur = None
            continue
        if raw.startswith("- "):
            for chunk in _split_inline(raw[2:]):
                k, v = _kv(chunk)
                if k:
                    # first value wins; later '·' chunks are separate fields
                    cur["fields"].setdefault(k, v)
    if cur:
        scenarios.append(cur)
    return scenarios


def parse_k_table(text: str) -> list[dict]:
    """Group K is a markdown table, not '###' blocks."""
    out = []
    row_re = re.compile(
        r"^\|\s*(K\d+)\s*\|\s*([a-z0-9_.]+)\s*\|\s*(user_\w+)\s*\|"
        r"\s*([^|]*)\|\s*([^|]*)\|\s*([^|]*)\|\s*(\w+)\s*\|"
    )
    for line in (_clean(l) for l in text.split("\n")):
        m = row_re.match(line.strip())
        if not m:
            continue
        out.append({
            "coverage_id": m.group(1),
            "scenario_id": m.group(2),
            "fields": {
                "event_type": m.group(3).strip(),
                "intent": m.group(4).strip(),
                "render_intent": m.group(5).strip(),
                "output_widget": m.group(6).strip(),
                "eval_split": m.group(7).strip(),
                # K rows describe a widget interaction, not typed phrasings.
                "user_prompts": "",
            },
        })
    return out


# ── preconditions -> slot_state ────────────────────────────────────────────
# The catalog states preconditions in prose ("region + dates + party",
# ">=2 hotels in context").  A row seeded with an empty slot_state can only
# ever exercise the cold-start path: a first build of this corpus produced 235
# rows that ALL resolved to collect_missing with zero tool requests, and every
# acceptance gate still reported PASS.  So the preconditions are materialised
# here into the slot keys the oracle actually branches on.
#
# Fixture values are shared so rows stay comparable across scenarios.
FIXTURE_REGION = {"label": "Paris", "city_code": "PAR", "country_code": "FR"}
FIXTURE_CHECK_IN = "2026-09-10"
FIXTURE_CHECK_OUT = "2026-09-14"
FIXTURE_PARTY = {"adults": 2}
FIXTURE_OFFER = "off_fixture_0001"
FIXTURE_HOTEL = "hot_fixture_0001"

# What state each coverage cell assumes on entry.  Explicit per cell rather
# than inferred from prose: the prose is not machine-reliable, and a wrong
# guess here silently changes the label the oracle derives.
#   region / dates / party / places / flights / picked_flight / hotels /
#   picked_hotel / order
SLOT_PRESETS = {
    # A — open discovery: cold start by definition.
    "A1": (), "A2": (), "A3": (), "A4": (), "A5": (), "A6": (),
    # B — place resolution: B6 refers back to a prior place_list.
    "B1": (), "B2": (), "B3": ("region",), "B4": (), "B5": (),
    "B6": ("region", "places"),
    # C — slot collection: partial by design.
    "C1": (), "C2": (), "C3": (), "C4": ("region", "places"), "C5": (),
    "C6": ("region", "places"), "C7": (),
    # D — flights: searchable once region+dates+party are known.
    "D1": ("region", "dates", "party", "places"),
    "D2": ("region", "dates", "party", "places"),
    "D3": ("region", "dates", "party", "places"),
    "D4": ("region", "dates", "party", "places"),
    "D5": ("region", "dates", "party", "places"),
    "D6": ("region", "dates", "party", "places", "flights", "picked_flight"),
    # E — hotels: the catalog reaches these directly from region+dates+party.
    "E1": ("region", "dates", "party", "places"),
    "E2": ("region", "dates", "party", "places", "hotels"),
    "E3": ("region", "dates", "party", "places", "hotels"),
    "E4": ("region", "dates", "party", "places", "hotels"),
    "E5": ("region", "dates", "party", "places", "hotels"),
    "E6": ("region", "dates", "party", "places", "hotels", "picked_hotel"),
    "E7": ("region", "dates", "party", "places"),
    # F — activities / POI.
    "F1": ("region", "places"),
    "F2": ("region", "dates", "party", "places"),
    "F3": ("region", "dates", "party", "places"),
    "F4": ("region", "dates", "party", "places"),
    "F5": ("region", "places"),
    # G — transfers.
    "G1": ("region", "dates", "party", "places"),
    "G2": ("region", "dates", "party", "places"),
    "G3": ("region", "dates", "party", "places"),
    "G4": ("region", "dates", "party", "places"),
    "G5": ("region", "dates", "party", "places"),
    # H — itinerary views: need something selected to summarise.
    "H1": ("region", "dates", "party", "places", "flights", "picked_flight"),
    "H2": ("region", "dates", "party", "places", "flights", "picked_flight"),
    "H3": ("region", "dates", "party", "places", "flights", "picked_flight"),
    "H4": ("region", "dates", "party", "places"),
    "H5": ("region", "dates", "party", "places"),
    "H6": ("region", "dates", "party"),
    # I — corrections: something already exists to correct.
    "I1": ("region", "dates", "party", "places", "flights"),
    "I2": ("region", "dates", "party", "places", "flights"),
    "I3": ("region", "dates", "party", "places", "flights"),
    "I4": ("region", "dates", "party", "places", "flights"),
    "I5": ("region", "dates", "party", "places", "flights"),
    "I6": ("region", "dates", "party", "places", "flights"),
    # J — safety: cold start; the point is the refusal, not the state.
    "J1": (), "J2": ("region", "dates", "party"), "J3": (), "J4": (),
    "J5": (), "J6": (),
    # K — widget CTA rows.
    "K1": ("region", "places"),
    "K2": ("region",), "K3": ("region", "dates"),
    "K4": ("region", "dates", "party", "places"),
    "K5": ("region", "dates", "party", "places", "flights"),
    "K6": ("region", "dates", "party", "places", "flights", "picked_flight"),
    "K7": ("region", "dates", "party", "places", "hotels"),
    "K8": ("region", "dates", "party", "places", "hotels", "picked_hotel"),
    "K9": ("region", "dates", "party", "places"),
    "K10": ("region", "dates", "party", "places", "flights", "picked_flight"),
    # L — booking management (L1 live retrieval; L2-6 roadmap).
    "L1": ("region", "dates", "party", "places", "flights", "picked_flight", "order"),
    "L2": ("region", "dates", "party", "places", "flights", "picked_flight", "order"),
    "L3": ("region", "dates", "party", "places", "hotels", "picked_hotel"),
    "L4": ("region", "dates", "party", "places", "flights", "picked_flight", "order"),
    "L5": ("region", "dates", "party", "places", "flights", "picked_flight", "order"),
    "L6": ("region", "dates", "party", "places", "flights", "picked_flight", "order"),
    # M / N / O — roadmap.
    "M1": ("region", "dates", "party"), "M2": ("region", "dates", "party"),
    "N1": ("region", "dates"), "N2": ("region", "dates"),
    "O1": ("region", "dates", "party"), "O2": ("region", "dates", "party"),
}


def slot_state_for(cell: str) -> dict:
    parts = SLOT_PRESETS.get(cell, ())
    st: dict = {}
    if "region" in parts:
        st["region"] = dict(FIXTURE_REGION)
    if "dates" in parts:
        st["check_in_date"] = FIXTURE_CHECK_IN
        st["check_out_date"] = FIXTURE_CHECK_OUT
    if "party" in parts:
        st["party"] = dict(FIXTURE_PARTY)
    if "places" in parts:
        st["places_seen"] = [FIXTURE_REGION["label"]]
    if "flights" in parts:
        st["flight_search_results"] = [FIXTURE_OFFER]
    if "picked_flight" in parts:
        st["picked_flight_offer_id"] = FIXTURE_OFFER
    if "hotels" in parts:
        st["hotel_search_results"] = [FIXTURE_HOTEL]
    if "picked_hotel" in parts:
        st["picked_hotel_id"] = FIXTURE_HOTEL
    if "order" in parts:
        st["order_id"] = "ord_fixture_0001"
    return st


_INTENT_RE = re.compile(r"render_intent[:\s]+([a-z_]+)")


def declared_intent(sc: dict) -> str:
    f = sc["fields"]
    direct = (f.get("render_intent") or "").strip()
    if direct:
        m = re.match(r"^([a-z_]+)", direct)
        if m:
            return m.group(1)
    blob = " ".join(str(f.get(k) or "") for k in
                    ("expected_extract", "expected_render", "intent"))
    m = _INTENT_RE.search(blob)
    return m.group(1) if m else ""


def eval_split_for(sc: dict) -> str:
    cell = sc["coverage_id"]
    group = cell[0]
    declared = (sc["fields"].get("eval_split") or "").strip().lower()
    if group in ROADMAP_GROUPS or cell in ROADMAP_CELLS:
        return "roadmap"
    if declared in {"train", "eval", "both", "roadmap"}:
        return declared
    # Group J is safety: eval only, never train (PO playbook §4).
    if group == "J":
        return "eval"
    return "eval"


def build_rows(scenarios: list[dict]) -> list[dict]:
    rows = []
    for sc in scenarios:
        f = sc["fields"]
        cell = sc["coverage_id"]
        split = eval_split_for(sc)
        event_type = (f.get("event_type") or "user_message").strip()
        prompts = parse_prompts(f.get("user_prompts") or "")
        if not prompts:
            # Widget-driven turns (K rows, CTA scenarios) carry no typed text.
            # Emit ONE row whose payload is the widget action, so the cell is
            # still covered rather than silently dropped.
            prompts = [None]
        for idx, prompt in enumerate(prompts, start=1):
            if prompt is None:
                payload = dict(WIDGET_ACTIONS.get(cell, {"action_id": "confirm"}))
            else:
                payload = {"text": prompt}
            row_extra = {}
            # J4 / G5 declare a provider-sparse or provider-down precondition
            # ("tool_summary with zero results / provider error").  That is a
            # turn-level input, so it is carried explicitly rather than left to
            # the oracle to guess -- without it those cells cannot produce the
            # `error` intent the catalog declares.
            if cell in PROVIDER_ERROR_CELLS:
                row_extra["tool_error"] = True
            rows.append({
                **row_extra,
                # --- the 5 keys oracle.run_turn() consumes ---
                "id": f"{sc['scenario_id']}#{idx:02d}",
                "intent_label": sc["scenario_id"],
                "event_type": event_type,
                "event_payload": payload,
                "slot_state": slot_state_for(cell),
                # --- catalog provenance (additive; oracle ignores these) ---
                "scenario_id": sc["scenario_id"],
                "coverage_id": cell,
                "eval_split": split,
                "intent": f.get("intent", ""),
                "preconditions": f.get("preconditions", ""),
                "slots_to_fill": f.get("slots_to_fill", ""),
                "expected_extract": f.get("expected_extract", ""),
                "expected_render": f.get("expected_render", ""),
                "negative_constraints": f.get("negative_constraints", ""),
                "follow_up_question": f.get("follow_up_question", ""),
                "output_widget": f.get("output_widget", ""),
                "proposed_tool": f.get("proposed tool")
                or f.get("proposed tools")
                or f.get("proposed chain") or "",
                "declared_render_intent": declared_intent(sc),
                "source": "catalog",
            })
    return rows


def report(scenarios, rows):
    groups = {}
    for sc in scenarios:
        groups.setdefault(sc["coverage_id"][0], []).append(sc["coverage_id"])
    print(f"scenarios parsed : {len(scenarios)}")
    print(f"seed rows        : {len(rows)}")
    print()
    print("coverage by group (PO playbook §4 gate: every row A-K owns >=1):")
    for g in sorted(groups):
        cells = sorted(set(groups[g]))
        n = sum(1 for r in rows if r["coverage_id"][0] == g)
        print(f"  {g}  cells={len(cells):2d}  rows={n:3d}  {','.join(cells)}")
    print()
    splits = {}
    for r in rows:
        splits[r["eval_split"]] = splits.get(r["eval_split"], 0) + 1
    print("eval_split:", splits)
    live = [r for r in rows if r["eval_split"] != "roadmap"]
    print(f"corpus-eligible (non-roadmap): {len(live)}")
    j = [r for r in rows if r["coverage_id"][0] == "J"]
    bad_j = [r for r in j if r["eval_split"] not in ("eval", "roadmap")]
    print(f"safety gate — all J rows eval-only: {'PASS' if not bad_j else 'FAIL ' + str(bad_j)}")
    missing = [c for c in "ABCDEFGHIJK" if c not in groups]
    print(f"scenario-coverage gate — groups A-K all present: "
          f"{'PASS' if not missing else 'FAIL missing ' + ','.join(missing)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="parse + report only")
    args = ap.parse_args()

    text = open(CATALOG, encoding="utf-8").read()
    scenarios = parse_catalog(text) + parse_k_table(text)
    rows = build_rows(scenarios)
    report(scenarios, rows)

    if args.check:
        return 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
