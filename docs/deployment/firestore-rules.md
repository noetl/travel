# Firestore Rules

Round 5 ships `firestore.rules` as documentation and an operator starting
point. The rules are deliberately demo-permissive for reads and strict for
browser writes.

Deploy manually from a workstation with the Firebase CLI:

```bash
firebase deploy --only firestore:rules --project noetl-demo-19700101
```

The Muno frontend reads calendar widgets through the gateway subscription API.
Browser writes remain blocked in rules and go through the NoETL worker service
account via `mcp/firestore`.

Tighten the read rules when Firebase Auth lands:

- Restrict `users/{uid}` reads to the gateway service account and authenticated
  server-side checks.
- Keep direct browser writes disabled or validate them through a dedicated API.
- Prefer per-trip share documents for public itinerary links.
