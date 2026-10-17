# Firestore Rules

`firestore.rules` **denies all direct client access**: `allow read, write: if false`
on every document.

No client reads or writes Firestore directly. The apps (Adiona, the GUI) call the
gateway. Every Firestore read and write happens inside a playbook on the worker's
service account: `mcp/firestore`, and the planner's and intake's inline REST.
IAM governs that access; these rules do not.

## Deployment

Nothing deploys these rules automatically. Firebase is not enabled on
`shastaratech-noetl-prod` or `noetl-demo-19700101`, and neither project has a rules
release (checked 2026-10-16). With no ruleset, clients are already refused: an
anonymous REST read of `chat_threads` returns 403. The file is kept deny-all so that a
manual deploy can never open data up:

```bash
firebase deploy --only firestore:rules --project shastaratech-noetl-prod
```

## History

The v1 demo rules allowed public reads of `chat_threads/**`, `trips/**` and
`users/**`. They were never deployed. They were replaced with deny-all on
2026-10-16 (noetl/gateway advisory GHSA-qxw3-x3fw-qp2c, item 10).

If client access is ever needed, scope it per user (`request.auth.uid == uid`) or
per share document. Never reopen public reads.
