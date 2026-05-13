# Firestore Rules

Round 5 ships `firestore.rules` as documentation and an operator starting
point. The rules are deliberately demo-permissive for reads and strict for
browser writes.

Deploy manually from a workstation with the Firebase CLI:

```bash
firebase deploy --only firestore:rules --project noetl-demo-19700101
```

The v1 Muno frontend reads calendar widgets without Firebase Auth. Writes are
blocked in browser rules and go through the NoETL worker service account via
`mcp/firestore`.

For live calendar widgets, set the public Firebase web config at build time:

```bash
VITE_FIREBASE_API_KEY=...
VITE_FIREBASE_AUTH_DOMAIN=...
VITE_FIREBASE_PROJECT_ID=noetl-demo-19700101
```

These values enable unauthenticated reads only; they do not grant browser write
access under the v1 rules.

Tighten the read rules when Firebase Auth lands:

- Restrict `users/{uid}` reads to `request.auth.uid == uid`.
- Keep direct browser writes disabled or validate them through a dedicated API.
- Prefer per-trip share documents for public itinerary links.
