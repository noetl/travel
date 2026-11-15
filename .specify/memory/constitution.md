<!--
Sync Impact Report
- Version change: template → 1.0.0 (initial ratification)
- Principles added: I Validate Before Deploy; II Test on the Runtime That Runs It;
  III Prove the Read-Only Route; IV Honest Status; V One Change, One PR;
  VI noetl.ai Is the DSL Reference; VII Pin Before You Register; VIII Public Repo
- Sections added: Playbook Standards; Workflow; Governance
- Templates: spec/plan/tasks templates unchanged (travel-specific rules live here and in
  specs/001-travel-playbooks/spec.md)
- Follow-up TODOs: none
-->

# noetl/travel Constitution

This constitution governs every change to the NoETL playbooks in `noetl/travel`
(`playbooks/**`, registered as `muno/playbooks/*` and `travel/playbooks/*`), whether a
person or an AI agent makes it. The working how-to is
[`docs/playbooks/AGENT-GUIDE.md`](../../docs/playbooks/AGENT-GUIDE.md). If the two ever
disagree, this file wins, and the guide is fixed in the same PR.

## Core Principles

### I. Validate Before Deploy (NON-NEGOTIABLE)

A playbook MUST pass the published schema
(`https://noetl.ai/schema/v2/playbook.schema.json`, via
`scripts/validate_playbook_schema.py`) and the repo guards (`scripts/*_test.py`) before
it is registered anywhere. A failing check blocks the register. It is never waived.

*Rationale:* a playbook that doesn't parse, or names an unknown tool kind, fails at
dispatch time in prod, in front of users.

### II. Test on the Runtime That Runs It (NON-NEGOTIABLE)

A playbook with steps the local runtime can't execute (e.g. `kind: python`) MUST be
tested on the gateway (`noetl --context gke-prod run … --runtime distributed`), never
judged from a local run. Measured 2026-11-15: CLI 2.x silently skips python steps and
takes the first `when:` arc on unresolved templates, so a local run of `profile.yaml`
routes reads and saves alike to `begin_read` and never reaches Firestore. CLI 6.4.1
refuses the run.

*Rationale:* a local run of the profile playbook looks like "no data / wrong route"
whatever the code does, and has already sent a debugging effort the wrong way.

### III. Prove the Read-Only Route

A change to `playbooks/profile.yaml`, or to anything it calls, MUST be verified with a
`read_only: true` execution on the gateway. Its trace must show `begin_read` RAN and
`save_profile` skipped, and the Firestore document's `updateTime` must be unchanged. A
save is verified separately, with a QA account.

*Rationale:* a login-time read that writes is invisible in the UI and only shows up in
the trace and in `updateTime`.

### IV. Honest Status

"Merged", "registered" and "verified" are three different states. Report only what was
checked, and cite the execution id, catalog version/id and content digest. A claim
inferred from behaviour or logs is labelled as inferred until the catalog has been read
directly.

*Rationale:* a behaviour-based "prod is current" claim was once mistaken for a catalog
read. Labels prevent that.

### V. One Change, One PR

Each PR changes one playbook behaviour (plus its guard and docs), never pushes to
`main`, and stays inside its spec task's files.

### VI. noetl.ai Is the DSL Reference

DSL grammar, tool kinds, gates and limits come from noetl.ai: https://noetl.ai/ for
people, https://noetl.ai/llms.txt for agents, plus `/dsl/manifest.json` and
`/dsl/resource-model.json`. They don't come from memory or older playbooks. When the
reference and a running server disagree, the server's `GET /api/dsl/version` wins, and
the discrepancy is reported.

### VII. Pin Before You Register

Before registering over a catalog path, the current content is saved
(`noetl --context gke-prod catalog get <path>`) and its version, catalog id and digest
are recorded in the PR. Any regression means re-registering the pinned content.

### VIII. Public Repo

No secrets, tokens, `.env` files or personal data (real user ids, emails, profile
contents) go in commits, PRs or issues. Use `auth0|…xxxx`-style redaction.

## Playbook Standards

- `metadata.path` is the catalog path, and it is never renamed casually: the SPA calls
  it by name.
- `metadata.version` is present (the runtime stalls without it).
- In an exclusive arc set, no target may be reachable from a sibling target. The runtime
  marks losing siblings SKIPPED and never runs them later
  (`scripts/playbook_skip_topology_test.py` enforces this).
- Firestore access goes only through `automation/agents/mcp/firestore`. Profile saves use
  `merge: true`.

## Workflow

1. Write or update the spec task in `specs/001-travel-playbooks/` (`/speckit-specify`,
   `/speckit-plan`, `/speckit-tasks`).
2. Branch, then edit the YAML.
3. Validate (I) and run the guards.
4. Open the PR, with evidence.
5. After merge: pin (VII), register, verify (II, III), and record the result on the issue
   and in the PR.

## Governance

This constitution supersedes conflicting guidance in this repo. Amendments are made by
PR with a Sync Impact Report and a version bump: MAJOR for a removed or redefined
principle, MINOR for an added one, PATCH for wording. Reviewers check every playbook PR
against Principles I–VIII.

**Version**: 1.0.0 | **Ratified**: 2026-11-15 | **Last Amended**: 2026-11-15
