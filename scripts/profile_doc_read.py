#!/usr/bin/env python3
"""READ-ONLY: show what Firestore holds for one profile, users/{uid}.

Usage:  python3 scripts/profile_doc_read.py 'auth0|abc123' [--values]

Needs a gcloud login with read access (roles/datastore.viewer) on the project.
Prints createTime/updateTime and the field names (and value shapes); --values prints
the values too. A profile read must NOT change updateTime.

Every request goes through an allowlist that only permits GET, so this script cannot
write, update or delete anything.
"""
import json, subprocess, sys, urllib.parse, urllib.request

PROJECT = "shastaratech-noetl-prod"
ROOT = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"


def get(url):
    if urllib.parse.urlsplit(url).scheme != "https":
        raise RuntimeError("refusing non-https")
    token = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
    req = urllib.request.Request(url, method="GET", headers={"Authorization": f"Bearer {token}"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def decode(v):
    if "mapValue" in v:
        return {k: decode(x) for k, x in (v["mapValue"].get("fields") or {}).items()}
    if "arrayValue" in v:
        return [decode(x) for x in v["arrayValue"].get("values") or []]
    if "integerValue" in v:
        return int(v["integerValue"])
    for k in ("stringValue", "doubleValue", "booleanValue", "timestampValue", "nullValue"):
        if k in v:
            return v[k]


if len(sys.argv) < 2:
    sys.exit(__doc__)
uid = sys.argv[1]
doc = get(f"{ROOT}/users/{urllib.parse.quote(uid, safe='|')}")
if doc is None:
    print(f"users/{uid}: NOT FOUND (never saved)")
    sys.exit(0)
fields = {k: decode(v) for k, v in (doc.get("fields") or {}).items()}
print(f"users/{uid}  created={doc['createTime']}  updated={doc['updateTime']}  fields={len(fields)}")
for k in sorted(fields):
    v = fields[k]
    shape = f"{type(v).__name__}[{len(v)}]" if isinstance(v, (list, dict, str)) else repr(v)
    print(f"  {k:16} {json.dumps(v)[:200] if '--values' in sys.argv else shape}")
