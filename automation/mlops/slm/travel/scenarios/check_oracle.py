#!/usr/bin/env python3
"""Divergence report: oracle output vs the catalog's declared expectation.

This is the "Divergence -> spec update" step of the Product Owner playbook §5.
For every corpus row whose scenario declares a render_intent, run the oracle
and compare.  A disagreement is a finding about the ORACLE or the SPEC — it is
never fixed by editing a label.

Run:  python3 scenarios/check_oracle.py [--verbose]
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CORPUS = os.path.join(ROOT, "datasets", "seed", "travel_catalog_turns.jsonl")


def load_oracle():
    spec = importlib.util.spec_from_file_location(
        "oracle", os.path.join(ROOT, "oracle.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    m = load_oracle()
    rows = [json.loads(l) for l in open(CORPUS, encoding="utf-8")]
    live = [r for r in rows if r["eval_split"] != "roadmap"]

    agree = disagree = undeclared = errors = 0
    by_cell: dict[str, dict] = {}
    pairs = collections.Counter()
    tools_seen = set()
    intents_seen = set()

    for r in live:
        cell = r["coverage_id"]
        want = (r.get("declared_render_intent") or "").strip()
        try:
            out = m.run_turn(r)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            by_cell.setdefault(cell, {"agree": 0, "disagree": 0, "err": 0})["err"] += 1
            if args.verbose:
                print(f"  ERROR {r['id']}: {type(exc).__name__}: {exc}")
            continue
        ex = out.get("extract") or {}
        got = ((ex.get("render_intent") or {}).get("kind") or "").strip()
        intents_seen.add(got)
        for t in (ex.get("tool_requests") or []):
            tools_seen.add(t.get("tool"))
        slot = by_cell.setdefault(cell, {"agree": 0, "disagree": 0, "err": 0})
        if not want:
            undeclared += 1
            continue
        if want == got:
            agree += 1
            slot["agree"] += 1
        else:
            disagree += 1
            slot["disagree"] += 1
            pairs[(cell, want, got)] += 1

    scored = agree + disagree
    print("=" * 66)
    print("ORACLE vs CATALOG — divergence report")
    print("=" * 66)
    print(f"corpus rows          : {len(rows)} ({len(live)} live, "
          f"{len(rows) - len(live)} roadmap)")
    print(f"rows with a declared render_intent: {scored}")
    print(f"  agree              : {agree}"
          f"{f'  ({100*agree/scored:.1f}%)' if scored else ''}")
    print(f"  disagree           : {disagree}"
          f"{f'  ({100*disagree/scored:.1f}%)' if scored else ''}")
    print(f"rows with no declared intent (not scored): {undeclared}")
    print(f"oracle errors        : {errors}")
    print()
    print(f"distinct render intents the oracle produced: "
          f"{sorted(i for i in intents_seen if i)}")
    print(f"distinct tools the oracle requested        : "
          f"{sorted(t for t in tools_seen if t)}")
    print()

    # Reachability, not existence: TOOL_VOCAB / RENDER_INTENT_VOCAB declare
    # what the contract ALLOWS.  What matters for a corpus is what the oracle
    # can actually EMIT — an intent no branch produces has zero training
    # labels, however prominently the config lists it.
    unreachable_i = [i for i in m.RENDER_INTENT_VOCAB if i not in intents_seen]
    unreachable_t = [t for t in m.TOOL_VOCAB if t not in tools_seen]
    print(f"declared render intents the oracle CANNOT emit "
          f"({len(unreachable_i)}/{len(m.RENDER_INTENT_VOCAB)}): "
          f"{unreachable_i or 'none'}")
    print(f"declared tools the oracle CANNOT request "
          f"({len(unreachable_t)}/{len(m.TOOL_VOCAB)}): "
          f"{unreachable_t or 'none'}")
    print()

    if pairs:
        print("top disagreements (cell: declared -> oracle, count):")
        for (cell, want, got), n in pairs.most_common(20):
            print(f"  {cell:4s} {want:20s} -> {got:20s} x{n}")
        print()

    cells_clean = sorted(c for c, v in by_cell.items()
                         if v["disagree"] == 0 and v["err"] == 0)
    cells_bad = sorted(c for c, v in by_cell.items() if v["disagree"])
    print(f"cells fully agreeing ({len(cells_clean)}): {','.join(cells_clean)}")
    print(f"cells diverging      ({len(cells_bad)}): {','.join(cells_bad)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
