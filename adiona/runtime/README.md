# Rust runtime compatibility

The inspected Rust `PostgresTool` accepts positional `params: [...]`, but `noetl/server`'s `ToolSpec.params` accepts only an HTTP-style mapping. Registration stores YAML without rejecting it; execution then fails during tool parsing.

`0001-postgres-positional-params.patch` changes the server field to a JSON value that preserves either shape for the receiving tool's typed parser. It includes a regression test for both PostgreSQL arrays and HTTP objects. Apply only to the pinned server revision in `../docs/sources.md`, then build/test; production rollout and an upstream server PR are not part of this publication.

```bash
git -C "$NOETL_SOURCE_ROOT/server" apply "$TRAVEL_ROOT/adiona/runtime/0001-postgres-positional-params.patch"
cargo test --manifest-path "$NOETL_SOURCE_ROOT/server/orchestrate-core/Cargo.toml" positional_parameter_tests
```

The independent smallint result-decoding fix is [noetl/tools#104](https://github.com/noetl/tools/pull/104). This package also projects rows with PostgreSQL `to_jsonb`, so its tests run against the pinned unmodified tools revision while that fix is under review.

The current CLI's local interpreter does not execute PostgreSQL. Use the Rust distributed server/worker/EHDB validation below; do not count `noetl exec --runtime local` as a database test.

The runtime renders configuration at more than one stage. Raw request strings containing Jinja delimiters can otherwise be evaluated as templates on a later pass. Every request is JSON-serialized and base64-encoded in the parameter template, then decoded **inside the bound SQL parameter expression**. Encoding protects data fidelity between render stages; prepared parameter binding is what protects SQL. The real runtime regression includes literal `{{ request }}` and apostrophes.
