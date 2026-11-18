#!/usr/bin/env python3
"""Guard: an error rule (`spec.policy`) is only allowed inside a tool LIST.

The runtime fact, verified in source (noetl/travel#185, at server v3.165.1,
worker v6.19.0, tools v4.7.0):

  * A step whose `tool:` is a LIST is dispatched as one `task_sequence` command,
    and `task_sequence` (tools src/tools/task_sequence.rs) is the only code that
    reads `spec.policy.rules`. It consults them after each sub-task, including
    one that failed with a transport error.
  * A step whose `tool:` is a single mapping is dispatched as that tool's own
    kind. Its `spec` travels as opaque config that nothing reads; the server
    even renders the rule's `when` at dispatch, before `output` exists, so it
    arrives as `when: false`.
  * A failed single-tool step is therefore terminal: orchestrate-core skips its
    `next` arcs and emits `playbook.failed`.

profile.yaml's `suggest_pois` carried `do: continue` on a single `kind: playbook`
tool for weeks, and its header promised "never fails the save" on that basis.
This makes the rule mechanical: a `spec.policy` on a single tool fails this check.
"""
import glob
import sys

import yaml


def offenders(doc, path):
    out = []
    for step in (doc.get("workflow") or []) if isinstance(doc, dict) else []:
        if not isinstance(step, dict):
            continue
        tool = step.get("tool")
        if isinstance(tool, dict):
            spec = tool.get("spec")
            if isinstance(spec, dict) and "policy" in spec:
                out.append(f"{path}: step '{step.get('step')}' has tool.spec.policy on a SINGLE tool "
                           f"(never evaluated; make `tool:` a one-item list)")
    return out


def self_test():
    bad = {"workflow": [{"step": "s", "tool": {"kind": "playbook", "spec": {"policy": {"rules": []}}}}]}
    good = {"workflow": [{"step": "s", "tool": [{"t": {"kind": "playbook", "spec": {"policy": {"rules": []}}}}]}]}
    assert offenders(bad, "bad"), "the guard must flag a single-tool policy"
    assert not offenders(good, "good"), "a policy inside a tool list is valid"


def main():
    self_test()
    files = sorted(glob.glob("playbooks/**/*.yaml", recursive=True) + glob.glob("playbooks/**/*.yml", recursive=True))
    if len(files) < 3:
        print(f"FAIL: only {len(files)} playbook file(s) found; run from the repo root")
        return 1
    problems = []
    for f in files:
        with open(f) as fh:
            try:
                docs = list(yaml.safe_load_all(fh))
            except yaml.YAMLError:
                continue  # schema/parse problems belong to validate_playbook_schema.py
        for d in docs:
            problems += offenders(d, f)
    for p in problems:
        print("FAIL", p)
    print(f"checked {len(files)} playbook file(s); single-tool policy rules: {len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
