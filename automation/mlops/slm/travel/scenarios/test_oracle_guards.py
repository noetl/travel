#!/usr/bin/env python3
"""Guards on the oracle. Run: python3 scenarios/test_oracle_guards.py

These exist because the divergence score in check_oracle.py is only meaningful
if the oracle is deriving its answer from the turn.  An oracle that peeked at
`declared_render_intent` (or keyed on `scenario_id` / `coverage_id`) would
score 100% and teach the model nothing — the score would be measuring itself.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CORPUS = os.path.join(ROOT, "datasets", "seed", "travel_catalog_turns.jsonl")

# Fields that exist on a corpus row for provenance/scoring and that the oracle
# must never consult.
FORBIDDEN = (
    "scenario_id", "coverage_id", "declared_render_intent", "eval_split",
    "expected_extract", "expected_render", "output_widget", "intent",
    "negative_constraints", "follow_up_question", "source", "proposed_tool",
    "preconditions", "slots_to_fill",
)


def load_oracle():
    spec = importlib.util.spec_from_file_location(
        "oracle", os.path.join(ROOT, "oracle.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_source_never_names_a_catalog_field(m) -> list[str]:
    """Static check: the oracle's source must not mention the fields at all."""
    src = open(os.path.join(ROOT, "oracle.py"), encoding="utf-8").read()
    # strip comments/docstrings crudely — a mention in prose is fine, a read is
    # not, and the distinguishing token is the subscript/get form.
    bad = []
    for f in FORBIDDEN:
        for form in (f'"{f}"', f"'{f}'"):
            if form in src:
                bad.append(f"oracle.py references {form}")
    return bad


def test_stripping_catalog_fields_changes_nothing(m) -> list[str]:
    """Behavioural check, which is the one that actually binds.

    Run every corpus row twice: once as-is, once with every provenance field
    deleted.  If any output differs, the oracle read something it must not.
    """
    bad = []
    rows = [json.loads(l) for l in open(CORPUS, encoding="utf-8")]
    for r in rows:
        stripped = {k: v for k, v in r.items() if k not in FORBIDDEN}
        try:
            a = m.run_turn(r)
            b = m.run_turn(stripped)
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{r.get('id')}: raised {type(exc).__name__}: {exc}")
            continue
        if json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True):
            bad.append(f"{r.get('id')}: output changed when provenance fields "
                       f"were removed")
    return bad


def test_every_declared_value_is_in_vocab(m) -> list[str]:
    bad = []
    rows = [json.loads(l) for l in open(CORPUS, encoding="utf-8")]
    for r in rows:
        out = m.run_turn(r)
        ex = out.get("extract") or {}
        kind = (ex.get("render_intent") or {}).get("kind")
        if kind and kind not in m.RENDER_INTENT_VOCAB:
            bad.append(f"{r.get('id')}: render_intent {kind!r} not in vocab")
        for t in (ex.get("tool_requests") or []):
            if t.get("tool") not in m.TOOL_VOCAB:
                bad.append(f"{r.get('id')}: tool {t.get('tool')!r} not in vocab")
    return bad


def main() -> int:
    m = load_oracle()
    failures = 0
    for fn in (test_source_never_names_a_catalog_field,
               test_stripping_catalog_fields_changes_nothing,
               test_every_declared_value_is_in_vocab):
        bad = fn(m)
        name = fn.__name__
        if bad:
            failures += 1
            print(f"FAIL {name} ({len(bad)})")
            for b in bad[:8]:
                print(f"       {b}")
        else:
            print(f"PASS {name}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
