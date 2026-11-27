#!/usr/bin/env python3
"""Render playbooks/payments.yaml and playbooks/payments-webhook.yaml.

The payments steps share one Python core (Firestore CAS, the test-mode Stripe
client, re-pricing, money). NoETL python steps can't import a shared module, so
the core is pasted into each step's `code:` here instead of being copied by hand.
`# @@INCLUDE a.py b.py@@` lines in playbooks/payments/*.yaml.in are replaced by
those files from playbooks/payments/, indented to the marker's column.

  python3 scripts/build_payments_playbooks.py          # write
  python3 scripts/build_payments_playbooks.py --check  # exit 1 if out of date
"""
import os
import re
import sys

SRC = "playbooks/payments"
OUT = {"payments.yaml.in": "playbooks/payments.yaml",
       "payments-webhook.yaml.in": "playbooks/payments-webhook.yaml"}
MARK = re.compile(r"^(\s*)# @@INCLUDE ([^@]+)@@\s*$")


def render(template):
    out = []
    for line in open(os.path.join(SRC, template)).read().splitlines():
        m = MARK.match(line)
        if not m:
            out.append(line)
            continue
        indent = m.group(1)
        for name in m.group(2).split():
            for src_line in open(os.path.join(SRC, name)).read().splitlines():
                out.append((indent + src_line) if src_line.strip() else "")
    return "\n".join(out) + "\n"


def main():
    check = "--check" in sys.argv
    stale = []
    for template, target in OUT.items():
        text = render(template)
        current = open(target).read() if os.path.exists(target) else ""
        if current != text:
            stale.append(target)
            if not check:
                open(target, "w").write(text)
    if check and stale:
        print("STALE (run scripts/build_payments_playbooks.py): " + ", ".join(stale))
        return 1
    print(("up to date: " if check else "wrote: ") + ", ".join(OUT.values()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
