#!/usr/bin/env python3
"""Guard: the generated payments playbooks match their sources.

playbooks/payments.yaml and playbooks/payments-webhook.yaml are rendered from
playbooks/payments/ by scripts/build_payments_playbooks.py, because the shared
core (Firestore CAS, the test-mode Stripe client) is pasted into three python
steps. A hand edit to a generated `code:` block, or a source edit without a
re-render, would make the registered playbook differ from the reviewed source.
"""
import subprocess
import sys

r = subprocess.run([sys.executable, "scripts/build_payments_playbooks.py", "--check"],
                   capture_output=True, text=True)
print(r.stdout.strip() or r.stderr.strip())
if r.returncode != 0:
    print("FAIL payments playbooks are stale")
    sys.exit(1)
print("PASS payments playbooks are generated from playbooks/payments/")
