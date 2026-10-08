# The travel business catalog, on Firestore

The domain catalog for muno/travel — hotels, lodging units, tours, categories,
attributes, media, bundles, reservations — lives in **Google Firestore** and is
reached from playbooks through the Firestore MCP connector.

It is **not** the NoETL internal catalog, and the distinction is the whole point of
this page.

## Two catalogs, one word

| | **internal catalog** | **business catalog** — this page |
| :-- | :-- | :-- |
| holds | NoETL's own objects: `playbook`, `credential`, `mcp`, `agent`, `memory`, `subscription` | domain data: items, categories, attributes, images, bundles, reservations |
| storage | **EHDB only.** No external datastore, ever. | **Firestore** (this domain's choice; another domain could pick anything) |
| interface | `/api/catalog/*` on the NoETL server | a **playbook step** → `automation/agents/mcp/firestore` |
| scales with | how many things NoETL knows about | how much domain data a tenant has |
| owned by | the platform | this application |

> **The internal catalog holds the playbook that reads the business data. It never
> holds the business data.**

Nothing on this page goes into EHDB. A domain entity in the internal catalog is a
defect, not an optimisation.

## What already exists (measured, 2026-10-07)

Do not build a Firestore connector. One is already registered and serving.

| | |
| :-- | :-- |
| connector | `automation/agents/mcp/firestore`, an MCP playbook in [noetl/ops](https://github.com/noetl/ops/blob/main/automation/agents/mcp/firestore.yaml) |
| registered | **version 11** in the prod catalog, 904 lines |
| transport | `kind: python` + `urllib` against **Firestore REST v1** — hand-rolled JSON value encoding so the worker image needs no `google-cloud-firestore` dependency |
| auth | **Workload Identity / ADC.** The worker's default service-account token is minted from the GKE metadata server. **No key, no secret, nothing in the keychain.** |
| project | `shastaratech-noetl-prod`, database `(default)`, `us-central1` |

### The ten tools it exposes

`get_doc` · `set_doc` · `delete_doc` · `query_collection` · `append_event` ·
`replay_events` · `batch_get_docs` · `batch_set_docs` · `batch_append_events` ·
`batch_write`

Called like any other child playbook:

```yaml
- step: read_item
  tool:
    kind: playbook
    path: automation/agents/mcp/firestore
    payload:
      method: tools/call
      tool: get_doc
      arguments:
        path: "catalog/v1/items/{{ workload.item_id }}"
```

⚠ **`kind: agent` is not a tool kind.** The server's `ToolKind` enum has 25 variants
and `agent` is not among them — it is explicitly in the reject list
(`orchestrate-core/src/playbook.rs`). An MCP provider is reached with
`kind: playbook` + `path:`. There is no `firestore` tool kind either, and this design
does not need one.

### What the connector cannot do

Measured against the registered v11 implementation, not the docstring. The model
below is designed to stay inside these limits.

| limit | consequence for a catalog |
| :-- | :-- |
| `where` supports only `=`, `<`, `<=`, `>`, `>=`, `array-contains`, composed with **AND** | no `in`, no `array-contains-any`, no `!=`, no `OR`. One category per query. |
| `from: [{collectionId}]` is built **without `allDescendants`** | **no collection-group queries.** A subcollection can only be queried under a known parent. |
| `limit` caps at 500 and there is **no cursor** (`startAt`/`offset`/`pageToken`) | a collection larger than 500 documents **cannot be fully read** through this tool. |
| `delete_doc` does not recurse — the schema says so explicitly | **no cascade.** See *Referential integrity* below. |

These are the four gaps to close before this catalog outgrows a single page of
results; they are specced in
[noetl/ai-meta#451](https://github.com/noetl/ai-meta/issues/451) and none of them
blocks the model below.

## The reference model, and why it is only a reference

The entity/relation shape is taken from a relational catalog (the adiona MySQL/
Postgres schema) because that schema solved this domain's modelling problem well.
What is borrowed is **structural**, not schematic:

- **one polymorphic entity** (`items`) with a type discriminator, instead of a table
  per sellable thing;
- an **EAV collapse** — `attributes` + `item_attributes` rather than a column per
  property;
- a **self-referencing taxonomy** — `categories.parent_id` + `category_types`;
- **localization split out of the entity** — the `_content` tables, keyed by
  `lang_code`;
- **M:N membership** via a join (`item_category`), and **composition** via bundles.

Its *tables* are not the target. Firestore has no joins, no foreign keys and no
recursive queries, so a faithful transcription would be unusable. Every relational
construct below is restated as a Firestore one.

## Collections

⚠⚠ **The root is `catalog/v1`, two segments, not `catalog`.** Firestore paths
**alternate** collection/document, so a **document** path has an **even** number of
segments and a **collection** path an **odd** one. With a one-segment root both shapes are
illegal:

| path | segments | what Firestore sees |
| :-- | --: | :-- |
| `catalog/items/itm_x` | 3 | a **collection** reference — rejected as a document |
| `catalog/items` | 2 | a **document** path — rejected as a collection |
| `catalog/v1/items/itm_x` | 4 | ✅ a document |
| `catalog/v1/items` | 3 | ✅ a collection |

This page specified the one-segment form, and the first live write rejected **all 24
documents** with

```text
Document name ".../documents/catalog/categories/cat_root" lacks "/" at index 90
INVALID_ARGUMENT
```

Nothing caught it earlier because no fixture can: the step bodies build strings, and a
string is a string. Only a write to Firestore could. `scripts/business_catalog_upsert_test.py`
now asserts the arity of every emitted path as the cheap stand-in. The intermediate `v1`
document need not exist — Firestore allows an implicit parent — and it gives the namespace
a version segment for free.

```text
catalog/v1/
  items/{item_id}                      ← the polymorphic entity
    content/{lang_code}                ← localized text, one doc per language
    images/{image_id}
    units/{unit_id}                    ← lodging_units: a specialization's detail rows
  categories/{category_id}
    content/{lang_code}
    images/{image_id}
  category_types/{category_type_id}
    content/{lang_code}
  attributes/{attribute_id}
    content/{lang_code}
  reservations/{reservation_id}
  languages/{lang_code}
  currencies/{currency_code}
    history/{effective_at}
```

Everything sits under a single `catalog/v1/` ancestor so the business catalog never
collides with the planner's conversational state (`chat_threads/`, `users/` — see
[data-model.md](data-model.md)).

### `catalog/items/{item_id}`

The one document a read path wants.

```json
{
  "item_type": "lodging",
  "status": "published",
  "provider": { "source": "hotelbeds", "external_id": "12345" },
  "category_ids": ["cat_beach", "cat_family", "cat_root"],
  "primary_category_id": "cat_beach",
  "attrs": { "star_rating": 4, "has_pool": true, "max_occupancy": 6 },
  "geo": { "lat": 36.71, "lng": -4.42, "country": "ES", "city": "Malaga" },
  "price_from": { "amount": 11500, "currency": "EUR" },
  "bundle": null,
  "default_lang": "en",
  "available_langs": ["en", "de", "ka"],
  "created_at": "2026-10-07T00:00:00Z",
  "updated_at": "2026-10-07T00:00:00Z"
}
```

Three deliberate choices:

- **`category_ids` is a flattened ancestor-closure array, not just direct parents.**
  A relational catalog answers "everything under Beach" with a recursive CTE.
  Firestore cannot, so the closure is materialised at write time and the query
  becomes one `array-contains`. The cost is a rewrite of the affected items when the
  taxonomy moves — which is rare, and is a batch job.
- **`attrs` is a map, not a subcollection.** Firestore auto-indexes `attrs.<key>`, so
  `attrs.has_pool == true` is queryable with no extra work, and the EAV rows arrive
  with the parent document in one read. The 1 MiB document ceiling is the bound; an
  item with thousands of attributes belongs in a subcollection instead.
- **`price_from` is an integer minor unit plus a currency code.** Never a float.

### `catalog/items/{item_id}/content/{lang_code}`

This is where localization actually belongs — in the business catalog, keyed by
language, next to the business data it translates.

```json
{
  "lang_code": "de",
  "name": "Strandhotel Malaga",
  "summary": "…",
  "description_html": "…",
  "updated_at": "2026-10-07T00:00:00Z"
}
```

The document id **is** the language code, so the localized read is a `get_doc` at a
computed path — no query, no index, no fallback logic beyond "try the requested
language, then `items/{id}.default_lang`". The parent's `available_langs` array lets
a caller avoid a 404 round trip.

⚠ Because the connector cannot do collection-group queries, "every item with German
content" is **not** expressible as one call. Ask it of the parent instead:
`where: [{field: available_langs, op: array-contains, value: "de"}]` on
`catalog/items`. That is why `available_langs` is denormalised onto the item.

### `catalog/categories/{category_id}`

```json
{
  "category_type_id": "ct_destination",
  "parent_id": "cat_root",
  "ancestor_ids": ["cat_root"],
  "depth": 1,
  "sort_order": 10,
  "item_count": 42,
  "status": "published"
}
```

`parent_id` carries the self-reference for walking up one level; `ancestor_ids`
materialises the whole path so a subtree query is again one `array-contains`.
`item_count` is denormalised because Firestore has no `COUNT(*)` through this
connector — and it is therefore a **representation**: it is true only while the
writer that maintains it runs. Treat a stale count as display-only and never gate a
decision on it.

### `catalog/reservations/{reservation_id}`

```json
{
  "item_id": "itm_123",
  "unit_id": "unit_7",
  "user_uid": "auth0|abc",
  "status": "confirmed",
  "window": { "from": "2026-11-01", "to": "2026-11-08" },
  "price": { "amount": 92000, "currency": "EUR" },
  "provider_ref": { "source": "hotelbeds", "booking_id": "…" },
  "created_at": "…"
}
```

⚠ Bookings are **sandbox/test only** — the HotelBeds `_is_sandbox` gate and the
Duffel test token. A reservation document is never evidence of a real purchase.

"My reservations" needs a per-user read, and Firestore cannot join, so the same
document is mirrored at `users/{uid}/reservations/{reservation_id}`. Write both in
one `batch_write`; they are two copies of one fact, and the mirror is a
representation of the top-level document, not an independent record.

## Relations: three shapes, and no integrity

Every foreign key in the relational reference becomes exactly one of:

| relational | Firestore | when |
| :-- | :-- | :-- |
| FK column | a **field holding an id or document path** | the child is read on its own and the parent is looked up occasionally (`reservations.item_id`) |
| FK + "find the many side" | a **denormalised array on the many side** | the query "all X for this Y" must work (`items.category_ids`) |
| FK with a dependent lifetime | a **subcollection** | the child is meaningless without the parent (`items/{id}/content/{lang}`) |

⚠⚠ **Firestore enforces none of it.** There is no `REFERENCES`, no `NOT NULL` across
documents, no `ON DELETE`. So:

- **`nullable` is advisory.** A missing field and a null field are different in
  Firestore and both occur; a reader must handle both.
- **Cardinality is advisory.** Nothing stops two documents claiming the same unique
  key.
- **`on_delete: cascade` must be written as playbook steps.** `delete_doc`
  deliberately does not recurse, so deleting an item leaves its `content/`,
  `images/` and `units/` subcollections as orphans that no query under the deleted
  parent will ever return — invisible, billed, and still readable by path. A delete
  playbook enumerates and deletes children first, then the parent.

Prefer **soft delete** (`status: "archived"`) over `delete_doc` for exactly this
reason, matching the platform's own `POST /api/catalog/restore` posture.

## Writes

One `batch_write` per logical change, never a sequence of `set_doc` hops. The
connector's `batch_write` takes `set_docs` + `set_docs_extra` and
`append_events` + `append_events_extra`, concatenated in order, and the planner
already depends on this to collapse four child dispatches into one — a measured
~14 s saving per turn on the read side alone.

Firestore's own limits still apply: **500 writes per commit**, and roughly **1
sustained write per second per document**. A bulk ingest of items is therefore
chunked at 500 and must not funnel through a single counter document — which is
the second reason `item_count` is advisory.

## Reading it from a playbook

```yaml
- step: list_items_in_category
  tool:
    kind: playbook
    path: automation/agents/mcp/firestore
    payload:
      method: tools/call
      tool: query_collection
      arguments:
        collection_path: catalog/v1/items
        where:
          - { field: status,       op: "=",              value: published }
          - { field: category_ids, op: array-contains,   value: "{{ workload.category_id }}" }
        order_by: { field: sort_order, direction: ASCENDING }
        limit: 100
```

A single AND-composed query with one `array-contains` is the shape the connector
supports, and it is the shape the model is built for.

⚠⚠ **Every query above needs a composite index, and none exist.** Firestore
auto-indexes single fields, but any query combining `array-contains` with another
filter or an `orderBy` needs a composite index declared up front; without one the
query fails at request time. Measured on `shastaratech-noetl-prod` on 2026-10-07:
**zero composite indexes are deployed, and the repo had no index declaration file at
all** — `firestore.rules` governs client access and says nothing about indexes.

[`firestore.indexes.json`](../../firestore.indexes.json) now declares the six this
model needs. It is a declaration, not a deployment: applying it is a prerequisite for
the first query, not a side effect of merging it.

```bash
firebase deploy --only firestore:indexes --project shastaratech-noetl-prod
```

## Security

`firestore.rules` governs direct client access; see
[firestore-rules.md](../deployment/firestore-rules.md). The business catalog is
served to the SPA **through playbooks**, not by direct client reads, so the catalog
collections should be closed to client access entirely — the worker reaches them
with its own service-account identity, which rules do not apply to.

## Related

- [data-model.md](data-model.md) — the planner's **conversational** Firestore state
  (`chat_threads/`, `users/`). Different concern, same database.
- [firestore-rules.md](../deployment/firestore-rules.md) — client-side access rules.
- `agents/rules/execution-model.md` in noetl/ai-meta — why a data touch belongs in a
  playbook step under its policy block, which is what makes this a business catalog
  rather than a platform one.
