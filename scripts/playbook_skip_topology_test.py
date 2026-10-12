#!/usr/bin/env python3
"""Guard: no playbook may route to a step its own branch already SKIPPED.

The runtime rule (noetl/server orchestrate-core), verified in source:

  * When a step's arcs are evaluated, every arc that does not win (an exclusive sibling
    that lost, or a `when` that was false) has its target marked `step.skipped`
    (orchestrator.rs pass 1).
  * `is_step_done` counts Skipped as done, like Completed and Failed (state.rs).
  * A later arc to a done step is dropped unless it is a loop back-edge
    (orchestrator.rs pass 2: `if state.is_step_done(next) && !is_loop_reentry { continue; }`).
  * A routing step that has a back-edge never emits skips.

So if step S can route to A or B, and the run that takes A can later reach B, then B was
skipped at S and the arc into it is silently dropped. Nothing fails; the execution just stops
dispatching and never reaches a terminal state.

profile.yaml shipped exactly this twice: `build_response` as a no-coordinates alternative
(fixed with `skip_suggestions`), then `load_profile` as the read-only alternative while
`save_profile -> load_profile` (every save stranded). This makes the rule mechanical instead of a
comment someone has to remember.
"""
import glob
import sys
from collections import defaultdict

import yaml


def arcs_of(step):
    nxt = step.get("next")
    if isinstance(nxt, dict):
        arcs = nxt.get("arcs") or []
    elif isinstance(nxt, list):
        arcs = nxt
    else:
        arcs = []
    return [a for a in arcs if isinstance(a, dict) and a.get("step")]


def violations(doc):
    steps = [s for s in (doc.get("workflow") or []) if isinstance(s, dict) and s.get("step")]
    graph = defaultdict(set)
    for s in steps:
        for a in arcs_of(s):
            graph[s["step"]].add(a["step"])

    def reach(src):
        seen, todo = set(), [src]
        while todo:
            for t in graph[todo.pop()]:
                if t not in seen:
                    seen.add(t)
                    todo.append(t)
        return seen

    out = []
    for s in steps:
        name = s["step"]
        targets = list(dict.fromkeys(a["step"] for a in arcs_of(s)))
        if len(targets) < 2:
            continue
        if name in reach(name):
            continue  # a routing step on a cycle never emits skips
        for winner in targets:
            downstream = reach(winner)
            for loser in targets:
                if loser != winner and loser in downstream:
                    out.append(f"{name}: when '{winner}' wins, '{loser}' is skipped, "
                               f"but '{winner}' later routes to it -> the run strands")
    return out


def check_doc(doc):
    return violations(doc)


if __name__ == "__main__":
    files = sorted(glob.glob("playbooks/**/*.yaml", recursive=True)
                   + glob.glob("qa/**/*.yaml", recursive=True))
    bad = 0
    checked = 0
    for f in files:
        try:
            doc = yaml.safe_load(open(f))
        except Exception as exc:
            # Never skip silently: an unparseable playbook would otherwise shrink the
            # denominator and read as a clean pass.
            bad += 1
            print(f"FAIL {f}: does not parse: {str(exc).splitlines()[0]}")
            continue
        if not isinstance(doc, dict) or "workflow" not in doc:
            continue
        checked += 1
        for v in violations(doc):
            bad += 1
            print(f"FAIL {f}: {v}")

    # Self-test: the rule must catch the two shapes profile.yaml actually shipped.
    stranded = {"workflow": [
        {"step": "validate", "next": {"spec": {"mode": "exclusive"}, "arcs": [
            {"when": "r", "step": "load"}, {"when": "ok", "step": "save"}, {"step": "reject"}]}},
        {"step": "save", "next": {"arcs": [{"step": "load"}]}},
        {"step": "load", "next": {"arcs": [{"step": "end"}]}},
        {"step": "reject", "next": {"arcs": [{"step": "end"}]}},
        {"step": "end"}]}
    fixed = {"workflow": [
        {"step": "validate", "next": {"spec": {"mode": "exclusive"}, "arcs": [
            {"when": "r", "step": "begin_read"}, {"when": "ok", "step": "save"}, {"step": "reject"}]}},
        {"step": "begin_read", "next": {"arcs": [{"step": "load"}]}},
        {"step": "save", "next": {"arcs": [{"step": "load"}]}},
        {"step": "load", "next": {"arcs": [{"step": "end"}]}},
        {"step": "reject", "next": {"arcs": [{"step": "end"}]}},
        {"step": "end"}]}
    selftest_ok = bool(violations(stranded)) and not violations(fixed)
    print(f"self-test (catches the stranded shape, passes the fixed one): {'OK' if selftest_ok else 'FAIL'}")
    print(f"{checked} playbooks checked, {bad} violation(s)")
    if checked < 4:
        print("FAIL: fewer than 4 playbooks found -- the glob is wrong")
        sys.exit(1)
    sys.exit(1 if bad or not selftest_ok else 0)
