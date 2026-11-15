#!/usr/bin/env python3
"""Validate NoETL playbook YAML against the published schema at noetl.ai.

Usage:  python3 scripts/validate_playbook_schema.py playbooks/profile.yaml [more.yaml ...]
Exit 0 when every file validates, 1 otherwise. Needs: pip install pyyaml jsonschema

Run this BEFORE registering a playbook (docs/playbooks/AGENT-GUIDE.md).
Schema: https://noetl.ai/schema/v2/playbook.schema.json (JSON Schema draft 2020-12).
"""
import json, sys, urllib.request
import yaml
from jsonschema import Draft202012Validator

SCHEMA_URL = "https://noetl.ai/schema/v2/playbook.schema.json"
# noetl.ai sits behind Cloudflare, which refuses urllib's default User-Agent (403).
req = urllib.request.Request(SCHEMA_URL, headers={"User-Agent": "noetl-playbook-validate/1.0"})
schema = json.load(urllib.request.urlopen(req, timeout=20))
validator = Draft202012Validator(schema)
bad = 0
for path in sys.argv[1:]:
    doc = yaml.safe_load(open(path))
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    if errors:
        bad += 1
        print(f"FAIL {path}: {len(errors)} error(s)")
        for e in errors[:20]:
            print("   at", "/".join(str(p) for p in e.absolute_path) or "<root>", "->", e.message[:200])
    else:
        print(f"OK   {path}")
sys.exit(1 if bad else 0)
