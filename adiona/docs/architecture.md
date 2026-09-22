# Architecture and boundaries

Adiona's MySQL model is the business-schema source. PostgreSQL 19 is the target; see [target/version policy](postgresql19.md). Business queries and transaction composition live in NoETL YAML; there is no Python backend, mock server, or new production Rust service. The Rust code here is a validation adapter calling upstream `noetl-tools`, plus a minimal server parser compatibility patch.

## Database and orchestration

Each operation is a single prepared SQL statement. PostgreSQL data-modifying CTEs make item plus default translation creation atomic. All caller data enters through a bound base64 JSON parameter, decoded with `convert_from(decode($1::text,'base64'),'UTF8')::jsonb`; JSON extraction and casts happen in PostgreSQL. Encoding prevents later runtime rendering stages from treating literal template delimiters inside input as expressions. SQL text, table names, credential aliases and schema names are static. User input never becomes SQL syntax.

NoETL returns `output.data.rows[].result`, a JSON object per row. The explicit `to_jsonb` row projection avoids the inspected Rust tool's missing `int2` decoder. Monetary prices stay integer cents; exchange rates use exact numeric storage. API consumers must preserve 64-bit IDs (JavaScript numbers cannot represent every bigint); production client envelopes should encode large IDs as strings before exposure.

`provision.yaml` takes a transaction-scoped advisory lock, applies an immutable version once, and records its SHA-256. A failed DDL statement rolls back the whole DO block. Reapplication verifies the ledger checksum and preserves business data. This checks migration identity, not arbitrary manual schema drift. Future changes need new numbered ledger entries; do not edit an applied migration. Existing source dumps must be deduplicated and imported separately after reconciliation; provisioning contains no source/customer data.

The separate `reset.yaml` is destructive and refuses any database other than `adiona_validation`. Never register reset in the normal application catalog. It drops the target and migration schemas only. `source_postgres_fixture.yaml` provisions the supplied PostgreSQL test table separately and is optional, validation-only.

## Identity and authorization

`adiona_actor` is a **trusted deployment credential alias**, never a workload argument. `adiona_migrator` is a separate administrative connection. Every actor connection uses a non-owner, non-superuser, non-BYPASSRLS PostgreSQL login granted `adiona_runtime`. A privileged operator binds that login to a user/permission in `adiona.principals`. `session_user`, not a caller-provided user ID, determines the actor. An unmapped runtime login has no visible business rows. A provider can mutate only its own items and children. Customers can read the catalog and their own profile/identity metadata. Taxonomy and identity linking are administrator-only. Self-service profile updates cannot change email, roles, provider subject, or other protected fields, including through direct SQL.

Database RLS is defense in depth for each connection; authorization predicates in playbooks give clearer errors. `item_content.provider_id` is a deliberate denormalized ownership key with a composite foreign key to `(items.item_id, items.provider_id)`. It permits RLS to authorize a default translation created in the same CTE as its new item; a snapshot-based parent lookup cannot see that just-inserted row.

The actor identity helpers are narrowly scoped SECURITY DEFINER functions with an empty search path. The database contains declarative constraints, RLS policies and a security-invariant trigger, not a second business command API. The owner bypasses RLS and is used only for provisioning/operator tasks. Never use the migration credential for application calls.

This package has **no public API/gateway binding yet**. Do not bind a shared administrator alias to untrusted end users. For per-user use, a trusted gateway must verify the identity token, select an authorized principal-specific credential/catalog deployment and restrict execution paths and credential access. The fixed example alias models one deployment identity; it is not a multi-user impersonation mechanism. Identity linking requires verified provider evidence handled at that gateway; accepting a submitted subject or email is not authentication.

The source backend used Auth0 RS256 verification, not Firebase. Keep provider-neutral `(method,id)` subject linkage. Firebase is optional after issuer, audience, signature, expiry and revocation checks plus account-linking policy are implemented. No fake API token minting or source access/refresh tokens are migrated; use supported NoETL credentials for integration secrets and an optional opaque `credential_ref`.

## Conflicts and retries

Natural keys and `ON CONFLICT` make retries converge to the same entity ID. Upserts replace the fields listed by each playbook: they are not JSON Merge Patch; omitted nullable fields become null. `item_update` changes price without rewriting translations. Concurrent updates to the same key follow PostgreSQL ordering; there is no client optimistic-version contract yet. Creation timestamps remain stable; profile modification timestamps may advance on retries. This is convergent persistence, not an exactly-once HTTP response cache.

Graph mutations (`bundle_link`, category parent setters) require SERIALIZABLE connections and reject detected cycles. Set `default_transaction_isolation='serializable'` on the actual login in the target database; group-role settings are not inherited. Retry the entire operation on SQLSTATE 40001 or 40P01, with bounded backoff. A PostgreSQL foreign-key, validation or permission error is permanent and must not be retried blindly. The integration suite retries serialization/deadlock conflicts for concurrent upserts. No transaction is held across NoETL steps or borrowed pool connections.

Deletes are restrictive and explicit. References must be removed first; provisioning and CRUD do not cascade through business records. A missing or inaccessible target produces zero rows for reads/deletes/selected updates, avoiding an existence leak. Invalid inserts and guarded actions fail. Multi-request deletion sequences are not an atomic aggregate delete API.

## Storage and hospitality

PostgreSQL fits the actual relational model: foreign keys, localized content, many-to-many category links, bundles, integer prices, and atomic writes. JSONB is used for bound requests/output, not as a replacement for the relational model. MySQL remains the source for migration; PostgreSQL's transactional DDL and RLS are useful target features.

Item/category image URI columns remain storage-provider neutral. GCS is a suitable object-store option, but bucket IAM, signed uploads, object existence checks, scanning, and lifecycle deletion are not implemented. No object storage was contacted. Catalog IDs/relationships stay in PostgreSQL; blobs do not.

Lodging can be represented as product/service items with categories and attributes. Inventory by date, reservation state transitions, payments, taxes, outbox messages, refunds and channel synchronization need additional domain migrations/playbooks. The removed hospitality mock does not establish those guarantees. Specialized legacy tour/car availability and pricing procedures remain explicit migration gaps, not approximations hidden behind generic catalog search.
