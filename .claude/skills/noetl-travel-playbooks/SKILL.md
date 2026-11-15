---
name: noetl-travel-playbooks
description: Debug, update, validate and deploy NoETL playbooks for the Adiona/Muno travel app (noetl/travel `playbooks/*.yaml`, catalog paths `muno/playbooks/*`, e.g. the profile playbook that reads/writes Firestore `users/{uid}`). Use when a travel playbook "shows no data", reads write, a deploy needs checking, or a playbook must be edited and registered to the prod gateway (gateway.mestumre.dev). Covers local vs gateway runtime, gke-prod login, execution traces, Firestore inspection, noetl.ai schema validation, register + rollback.
---

# NoETL travel playbooks: debug, update, deploy

Full guide: `docs/playbooks/AGENT-GUIDE.md` in noetl/travel. This file is the working summary.
Bundled helpers live in `scripts/` next to this file. They're the same as `noetl/travel/scripts/`.

## Rules
1. Look up DSL on **noetl.ai** (start at https://noetl.ai/llms.txt). Don't write DSL from memory.
2. **Validate before registering:** `python3 scripts/validate_playbook_schema.py <file.yaml>` must print OK.
3. **Test on the gateway, not locally,** for any playbook with `kind: python` steps (profile, hotel-cards, …):
   - CLI 2.x silently skips python steps and treats unresolved `when:` as true, so reads AND saves take `begin_read`, and the Firestore child fails as a "local file". No data.
   - CLI 6.4.1 refuses to run them ("uses tool kinds the local runtime cannot run").
   - Local results say nothing about reads, writes or data. Use CLI ≥ 6.4.1 (`noetl --version`).
4. Pin → validate → register → verify (trace + Firestore) → record. "Registered" is not "verified".
5. Saves through the gateway write the **signed-in user's** profile (uid is bound to the session). Use a QA account.
6. One change per PR. Report status honestly.

## One-time setup
```bash
noetl context update gke-prod \
  --auth0-domain=shastara.us.auth0.com \
  --auth0-client-id=ECUiHFlhT9gAR1htdSdROWn59WA0lOCH \
  --auth0-redirect-uri=http://127.0.0.1:8765/callback
noetl --context gke-prod auth login --browser-pkce --pkce-port 8765
```
Don't set `--auth0-audience`. On a 401 "Invalid or expired session", log in again.

## Debug
```bash
# run a login-time profile read on the gateway
noetl --context gke-prod run catalog://muno/playbooks/profile --runtime distributed --json \
  --payload '{"uid":"ignored","profile":{},"read_only":true}'
python3 scripts/trace_execution.py <execution_id>         # RAN / skipped per step + catalog_id
python3 scripts/trace_execution.py <execution_id> --raw   # full JSON; workload.read_only says read vs save
python3 scripts/profile_doc_read.py 'auth0|<sub>'          # read-only Firestore users/{uid}; updateTime
```
- Correct read: `begin_read` RAN, `save_profile` skipped, `updateTime` unchanged.
- Correct save: `save_profile` RAN, `begin_read` skipped.
- The app's `[Profile] load/save response` console logs (with `executionId`) appear only in dev builds (`npm start`).

## Update + deploy (latest-wins catalog)
```bash
P=playbooks/profile.yaml; NAME=muno/playbooks/profile
noetl --context gke-prod catalog get $NAME > /tmp/profile.pin.json          # 0. rollback pin FIRST
python3 scripts/validate_playbook_schema.py $P                               # 1. must print OK
noetl --context gke-prod register playbook --file $P                         # 2. register (403 => ask the owner)
noetl --context gke-prod catalog get $NAME | python3 -c "import json,sys,hashlib;d=json.load(sys.stdin);print(d['version'],d['catalog_id'],hashlib.sha256(d['content'].encode()).hexdigest()[:16])"
shasum -a 256 $P                                                             # 3. digests must match
# 4. run + trace + Firestore check as in "Debug"
# rollback: re-register the pinned content
python3 -c "import json;open('/tmp/rollback.yaml','w').write(json.load(open('/tmp/profile.pin.json'))['content'])"
noetl --context gke-prod register playbook --file /tmp/rollback.yaml
```

## noetl.ai
- reference/explorer: https://noetl.ai/
- agents: https://noetl.ai/llms.txt
- schema: https://noetl.ai/schema/v2/playbook.schema.json
- manifest: https://noetl.ai/dsl/manifest.json
- resource model: https://noetl.ai/dsl/resource-model.json

noetl.ai answers every path with HTTP 200, so use these exact URLs. It and the gateway return 403 to Python's default User-Agent; set one.

## Gotchas
- **CLI identity ≠ app identity.** CLI logins use the `shastara` tenant, the app uses `mestumre-development`. Different `sub`, different `users/{uid}`.
- **Fields are stored twice,** camelCase + snake_case. The SPA reads camelCase first.
- **Saves merge top-level keys only;** nested maps and arrays are replaced whole.
- **Each register is a new version.** Executions use the latest. Rollback = re-register old content.
