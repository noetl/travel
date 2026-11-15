#!/usr/bin/env python3
"""Print which steps of a gateway execution RAN and which were SKIPPED.

Usage:  python3 scripts/trace_execution.py <execution_id> [--context gke-prod] [--raw]

Reads the session token the noetl CLI cached on `noetl --context gke-prod auth login`
(~/.noetl/config.yaml) and calls GET https://gateway.mestumre.dev/noetl/executions/{id},
which returns the execution and up to its 2000 most recent events. The token is never
printed.

For muno/playbooks/profile a correct login-time read (read_only: true) shows:
    begin_read RAN, save_profile skipped
and a save (read_only: false) shows the opposite. That is how to tell them apart.
"""
import json, os, sys, urllib.request

import yaml

args = [a for a in sys.argv[1:] if not a.startswith("--")]
ctx_name = sys.argv[sys.argv.index("--context") + 1] if "--context" in sys.argv else "gke-prod"
if "--context" in sys.argv:
    args.remove(ctx_name)
if len(args) != 1:
    sys.exit(__doc__)
execution_id = args[0]

cfg = yaml.safe_load(open(os.path.expanduser("~/.noetl/config.yaml")))
ctx = (cfg.get("contexts") or cfg).get(ctx_name) or {}
token, base = ctx.get("gateway_session_token"), (ctx.get("server_url") or "").rstrip("/")
if not token:
    sys.exit(f"no cached session for context {ctx_name!r}: run `noetl --context {ctx_name} auth login --browser-pkce --pkce-port 8765`")

# The gateway sits behind Cloudflare, which refuses urllib's default User-Agent (403).
req = urllib.request.Request(f"{base}/noetl/executions/{execution_id}",
                             headers={"Authorization": f"Bearer {token}",
                                      "User-Agent": "noetl-travel-trace/1.0"})
doc = json.load(urllib.request.urlopen(req, timeout=30))
if "--raw" in sys.argv:
    print(json.dumps(doc, indent=2))
    sys.exit(0)

print(f"execution {doc.get('execution_id')}  path={doc.get('path')}  status={doc.get('status')}  "
      f"catalog_id={doc.get('catalog_id')}")
order, state = [], {}
for e in doc.get("events") or []:
    node, kind = e.get("node_name") or e.get("node_id"), e.get("event_type")
    if not node or kind not in ("step.enter", "step.skipped", "command.completed", "command.failed"):
        continue
    if node not in state:
        order.append(node)
        state[node] = set()
    state[node].add(kind)
for node in order:
    s = state[node]
    verdict = "FAILED" if "command.failed" in s else "RAN" if ({"step.enter", "command.completed"} & s) else "skipped"
    print(f"  {node:22} {verdict}")
