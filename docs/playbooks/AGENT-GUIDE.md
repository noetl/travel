# Debugging, updating and deploying travel playbooks: a guide for AI agents

This is written for an AI coding agent (and the person driving it). Paste it into the
agent's prompt, or point the agent at this file. `AGENTS.md` at the repo root links here,
and the same content ships as an installable skill:
[`noetl-travel-playbooks.skill`](noetl-travel-playbooks.skill) (source:
[`.claude/skills/noetl-travel-playbooks/SKILL.md`](../../.claude/skills/noetl-travel-playbooks/SKILL.md)).

Everything below was run against the real system on 2026-11-15. Where something was
observed rather than designed, the guide says so.

---

## 0. The rules (read first)

1. **Use noetl.ai for the DSL.** Don't write NoETL DSL from memory. Look things up in
   the reference and validate against the published schema before every register (§5).
2. **Test playbooks that use `kind: python` on the gateway, not locally.** Local mode
   cannot run them (§1). `muno/playbooks/profile` is one of these.
3. **Validate → register → verify → record.** Never register without the schema check.
   Never call a deploy done without an execution trace showing the new behaviour.
4. **Keep a rollback pin.** Save the registered content *before* you register over it.
5. **Saves through the gateway write the signed-in user's own profile.** Use a QA
   account, never a real person's (§7).
6. **Report status honestly.** "Registered" is not "verified". Unverified claims are
   labelled as such.
7. **One change per PR.** Specs live in [`specs/001-travel-playbooks/`](../../specs/001-travel-playbooks/spec.md),
   and the rules in [`.specify/memory/constitution.md`](../../.specify/memory/constitution.md).

---

## 1. Environments: local vs the gateway

| | Local (`noetl run … --runtime local`) | Gateway (`noetl --context gke-prod run … --runtime distributed`) |
| :-- | :-- | :-- |
| where it runs | in-process on your machine | prod NoETL behind `https://gateway.mestumre.dev` |
| `kind: python` steps | **not supported** (see below) | run on the workers |
| child playbooks (`kind: playbook`, e.g. the Firestore provider) | looked up as **local files**, not the catalog | resolved from the prod catalog |
| Firestore | **none**: no credentials, no provider | `shastaratech-noetl-prod`, database `(default)` |
| playbook version | the YAML file you pass | the latest version registered in the prod catalog |

### Key finding: local does not honour the `read_only` route, so test reads on the gateway

`playbooks/profile.yaml` decides read vs save in `validate_input`, a `kind: python` step.
Its exclusive arcs are:

```yaml
- when: "{{ validate_input.ok and validate_input.read_only }}"
  step: begin_read          # read-only route
- when: "{{ validate_input.ok }}"
  step: save_profile        # write route
- step: reject_input
```

What the local runtime does with that, measured 2026-11-15 with the same payloads the
SPA sends:

- **CLI 2.x (2.17.0 observed):** python steps are **silently skipped** ("Tool not
  supported in local execution mode"). `validate_input` produces nothing, but the local
  condition check renders an unresolved template as a non-empty string, which counts as
  **true**, so the first arc wins. Reads **and saves** both take `begin_read`. The run then
  stops at `load_profile` with "Failed to read playbook file", because the child
  `automation/agents/mcp/firestore` is treated as a local path. **No Firestore read or
  write happens at all**, so locally you see **no data**.
- **CLI 6.4.1 (latest):** the run is **refused up front**: "Playbook 'profile' uses tool
  kinds the local runtime cannot run: … kind `python`", followed by
  "Run it on a cluster instead: `--runtime distributed`".

On the gateway the same input does the right thing. Here is the verified trace of a
login-time read, execution `380438259395731456`, profile v7:

```
validate_input  RAN
begin_read      RAN       <- read-only route
save_profile    skipped   <- no write
load_profile    RAN       (Firestore get_doc only)
build_response  RAN
```

**So:** a local run of `profile.yaml` tells you nothing about reads, saves or data. Debug
it on the gateway. Use local only for playbooks whose steps are all local-supported kinds
(`shell, http, playbook, duckdb, auth, sink, rhai, provider, agent, mcp, noop` in 6.4.1).
`noetl run` lists anything it can't run.

Check your CLI first: `noetl --version`. Use **6.4.1 or newer**. Older versions give
misleading results like the ones above. `exec` is a deprecated alias for `run`.

---

## 2. One-time setup (gke-prod context + login)

The `gke-prod` context points at the gateway. Operator logins use the `shastara` Auth0
tenant, whose native-app client the prod server accepts, with the PKCE callback on port
8765:

```bash
noetl context update gke-prod \
  --auth0-domain=shastara.us.auth0.com \
  --auth0-client-id=ECUiHFlhT9gAR1htdSdROWn59WA0lOCH \
  --auth0-redirect-uri=http://127.0.0.1:8765/callback

noetl --context gke-prod auth login --browser-pkce --pkce-port 8765
```

- If the context doesn't exist yet, use `noetl context add gke-prod --server-url=https://gateway.mestumre.dev --runtime=distributed …`
  with the same `--auth0-*` flags.
- **Don't set `--auth0-audience`.** The CLI forwards it to Auth0's `/authorize`, which
  rejects a non-API audience. The server checks the ID token's `aud`, which is already the
  client id.
- The redirect must be exactly `http://127.0.0.1:8765/callback`. That is what's registered
  in Auth0. If Auth0 says "Callback URL mismatch", the app's Allowed Callback URLs need it.
- When the session expires (HTTP 401 "Invalid or expired session"), run the login again.

Optional, for reading Firestore directly (§3.3): a gcloud login with
`roles/datastore.viewer` on `shastaratech-noetl-prod`.

---

## 3. Debugging a playbook

### 3.1 Run it on the gateway

```bash
# A login-time profile read, exactly what the SPA sends at login:
noetl --context gke-prod run catalog://muno/playbooks/profile --runtime distributed --json \
  --payload '{"uid":"ignored","profile":{},"read_only":true}'
# -> {"execution_id":"380…","status":"started"}

noetl --context gke-prod status <execution_id> --json     # COMPLETED / FAILED, step counts
```

The gateway replaces `uid` with the **signed-in user's** identity. That's why the value
above is ignored. See §7.

### 3.2 Read the event trace (which steps ran)

```bash
python3 scripts/trace_execution.py <execution_id>          # RAN / skipped per step
python3 scripts/trace_execution.py <execution_id> --raw    # full execution JSON
```

The script uses the session the CLI cached at login and calls
`GET https://gateway.mestumre.dev/noetl/executions/{id}`, which returns up to the 2000 most
recent events. It also prints the `catalog_id` that ran, so you can see which registered
version executed.

How to read a profile trace:

| run | `begin_read` | `save_profile` |
| :-- | :-- | :-- |
| login-time read (`read_only: true`) | RAN | skipped |
| save (`read_only: false`) | skipped | RAN |

⚠ A save that runs `save_profile` and skips `begin_read` is **correct**. Before
concluding "a read wrote", check that the execution you're reading was actually the read.
The execution's `workload.read_only` field says which it was (`--raw`).

### 3.3 Inspect the Firestore document

```bash
python3 scripts/profile_doc_read.py 'auth0|<sub>'           # field names + shapes, create/update times
python3 scripts/profile_doc_read.py 'auth0|<sub>' --values  # values too
```

The script is read-only (GET only). Profiles live at `users/{uid}`, where `uid` is the
Auth0 `sub`. A read must leave `updateTime` unchanged. A save changes it. The Firebase
console works too, if you have access.

### 3.4 Confirm the read-only route

1. Note the profile document's `updateTime` (§3.3).
2. Run the read from §3.1.
3. Trace it (§3.2): `begin_read` RAN and `save_profile` skipped.
4. Re-check `updateTime`. It must not have changed.

### 3.5 Getting the execution id from the app

The SPA (adiona/frontend) logs `[Profile] load response` and `[Profile] save response`,
including the `executionId`, **only in development builds**. Production builds
(travel.mestumre.dev) strip them. Run the app locally with `npm start`, pointed at the
same gateway, and copy the id from the browser console.

---

## 4. Updating and deploying a playbook

The prod catalog is **latest-wins**. Each register creates version N+1 under the same
path, and new executions use the latest version.

```bash
P=playbooks/profile.yaml
NAME=muno/playbooks/profile          # must match metadata.path in the YAML

# 0. Pin the current version for rollback (do this FIRST)
noetl --context gke-prod catalog get $NAME > /tmp/$(basename $P .yaml).pin.json
python3 -c "import json;d=json.load(open('/tmp/profile.pin.json'));print(d['version'],d['catalog_id'])"

# 1. Edit the YAML, then VALIDATE (must print OK; see §5)
python3 scripts/validate_playbook_schema.py $P
python3 scripts/profile_read_only_test.py           # repo guards (CI runs scripts/*_test.py)

# 2. Register the new version
noetl --context gke-prod register playbook --file $P

# 3. Verify it landed: new version / catalog_id, and the content is yours
noetl --context gke-prod catalog get $NAME | python3 -c \
 "import json,sys,hashlib;d=json.load(sys.stdin);print(d['version'],d['catalog_id'],hashlib.sha256(d['content'].encode()).hexdigest()[:16])"
shasum -a 256 $P                                      # should match the digest above

# 4. Verify behaviour: run it (§3.1), trace it (§3.2), and check Firestore (§3.3)
```

`playbooks/deployment/register-with-noetl.sh` is the repo's original register script. It
targets a directly reachable NoETL API (`NOETL_SERVER_URL`, default localhost) and only
registers the itinerary planner. For prod, use the `--context gke-prod` command above.

Registering on prod requires an operator session. If `register` returns 401, log in again
(§2). If it returns 403, your account isn't allowed to register. Ask the owner; don't
look for another route.

### Roll back

Re-register the pinned content. That creates a new version whose content equals the
old one:

```bash
python3 -c "import json;open('/tmp/rollback.yaml','w').write(json.load(open('/tmp/profile.pin.json'))['content'])"
noetl --context gke-prod register playbook --file /tmp/rollback.yaml
```

Then verify, exactly as in step 4.

---

## 5. NoETL DSL reference and validation (noetl.ai)

| | URL |
| :-- | :-- |
| DSL reference and explorer (the "NoETL DSL knowledge base" page) | https://noetl.ai/ |
| Same knowledge base, machine-readable for agents: grammar, tool kinds and their gates, limits | https://noetl.ai/llms.txt |
| Playbook JSON Schema (draft 2020-12) | https://noetl.ai/schema/v2/playbook.schema.json |
| Tool-kind manifest: enabled kinds, catalog features | https://noetl.ai/dsl/manifest.json |
| Resource and performance model: slots, limits, measured latency | https://noetl.ai/dsl/resource-model.json |
| Provenance: which server commit the artifacts were generated from | https://noetl.ai/dsl/source.json |

⚠ noetl.ai answers **every** path with the knowledge-base page (HTTP 200), so a mistyped
URL looks like it works. Use exactly the URLs above. Agents should start with `llms.txt`.

Validate against the published schema before every register:

```bash
pip install pyyaml jsonschema
python3 scripts/validate_playbook_schema.py playbooks/profile.yaml   # exit 0 = OK
```

The same check inline:

```python
import json, urllib.request, yaml
from jsonschema import Draft202012Validator
req = urllib.request.Request("https://noetl.ai/schema/v2/playbook.schema.json",
                             headers={"User-Agent": "playbook-validate/1.0"})  # see gotcha
schema = json.load(urllib.request.urlopen(req))
doc = yaml.safe_load(open("playbooks/profile.yaml"))
errors = list(Draft202012Validator(schema).iter_errors(doc))
print("OK" if not errors else "\n".join(f"{'/'.join(map(str,e.absolute_path))}: {e.message}" for e in errors))
```

- noetl.ai and the gateway sit behind Cloudflare, which returns **403 to Python's default
  User-Agent**. Set one, as above. `curl` works without it.
- A running server can also validate (`POST /api/dsl/validate`) and report its DSL
  version (`GET /api/dsl/version`), per `llms.txt`. The schema check above needs no
  server, so always run it.
- A playbook that passes the schema can still misbehave. Schema validity is necessary,
  not sufficient. The trace in §3.2 is the proof.

---

## 6. The profile playbook in one screen

- Catalog path: `muno/playbooks/profile`. Source: [`playbooks/profile.yaml`](../../playbooks/profile.yaml).
  The SPA calls it via the gateway's `executePlaybook` with
  `{uid, profile, read_only}`.
- Document: Firestore `users/{uid}`, where `uid` is the Auth0 `sub`.
- Save (`read_only: false`): `set_doc` with `merge: true`. **Top-level keys merge, but
  everything under a key is replaced.** Removing a booking works by sending the array
  without it. A top-level key can never be removed by a save.
- Read (`read_only: true`): `validate_input → begin_read → load_profile → build_response`,
  with no write.
- Response: `{ ok, uid, saved, read_only, found, found_after_write, profile, suggestions, suggestions_error }`.
  `saved: false` on a read is correct.
- Prod on 2026-11-15: **v7**, catalog id `736128634880000113`, byte-identical to `main`
  (#145).

---

## 7. Gotchas

- **Identity binding.** The gateway takes `uid` from the **verified session**, not from
  the request. A save writes the signed-in user's profile, whatever `uid` you send. Test
  saves with a dedicated QA account, never a real person's.
- **Your CLI identity is not your app identity.** `noetl` operator logins use the
  `shastara` tenant, while the travel app logs users in on the `mestumre-development`
  tenant. Same person, different `sub`, different `users/{uid}` document. A CLI read
  won't show your app profile.
- **Field duplication.** The SPA saves every field twice, camelCase (`displayName`,
  `homeCity`, `savedTrips`, `preferences.homeAirport`, …) plus snake_case copies
  (`display_name`, `home_city`, `saved_trips`, …). The SPA reads camelCase first. When the
  two disagree, camelCase wins.
- **Versions.** Each register is a new version (latest-wins). Executions don't pin a
  version in prod. Rollback means re-registering old content (§4).
- **Local runs** of python-step playbooks are meaningless (§1).
- **Stale local checkouts.** Older branches carry older `profile.yaml` copies. Compare
  against `origin/main`, or against what's registered (`catalog get`), never a local branch.
