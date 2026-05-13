# Figma PAT Setup

Muno reuses the `figma-access-token` GCP Secret Manager secret used by ai-meta. The helper script reads it without printing the token:

```bash
./scripts/figma_fetch.sh file <file_key> --depth 2
```

The token should include the minimum scopes needed for file reads. Future theme extraction needs `file_variables:read`.
