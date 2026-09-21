# Upstream syntax references

Inspected through the GitHub connector while preparing version 0.1. These immutable references establish the syntax basis; they do not establish compatibility with an uninspected deployed NoETL release.

| Reference | Revision / file |
|---|---|
| Canonical Playbook example | [noetl/e2e — v10_canonical_example.yaml](https://github.com/noetl/e2e/blob/1e41859c90069e63e3884fdc7555beced19deeda/fixtures/playbooks/v10_canonical_example.yaml) |
| HTTP retry example | [noetl/e2e — http_retry_status_code.yaml](https://github.com/noetl/e2e/blob/1e41859c90069e63e3884fdc7555beced19deeda/fixtures/playbooks/retry_test/http_retry_status_code.yaml) |
| HTTP JSON request example | [noetl/e2e — get_auth0_token.yaml](https://github.com/noetl/e2e/blob/1e41859c90069e63e3884fdc7555beced19deeda/fixtures/playbooks/api_integration/auth0/get_auth0_token.yaml) |
| Rust HTTP configuration and response envelope | [noetl/tools — http.rs](https://github.com/noetl/tools/blob/e66e49c27a3d9022c5bf5cab98423f13fbe5bc88/src/tools/http.rs) |

The inspected HTTP implementation exposes parsed JSON at `ToolResult.data.data`; its comment explicitly describes `output.data.data` usage in playbooks. This package captures that payload into `ctx` in the continuation policy. Some repository examples use different output paths and configuration nesting, so runtime verification remains necessary.

Remaining compatibility checks: installed version accepts executor declaration and metadata; templates preserve integer inputs and nested JSON; task policies see the expected status and response envelope; `then.set` updates execution context; error policy blocks downstream steps; retry attempts and backoff match expectations; terminal Python tool gets `payload`; catalog returns the intended terminal result. Validate crash/restart recovery independently of the local harness.

Repository integration also follows the [travel Rust migration guide](https://github.com/noetl/travel/wiki/python-to-rust-migration): every workflow includes a literal `start` step. The contract checker enforces its presence. Runtime execution remains unverified.
