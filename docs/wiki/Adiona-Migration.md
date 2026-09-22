# Adiona → NoETL migration

[Implementation and setup](https://github.com/noetl/travel/tree/feat/hospitality-playbooks/adiona) · [Draft PR #125](https://github.com/noetl/travel/pull/125) · [Source/schema/endpoint mapping](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/docs/migration-map.md) · [Validation evidence](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/docs/validation.md)

The business model comes from Adiona's modular **MySQL** definitions, converted to **PostgreSQL 19**. The supplied PostgreSQL source contains only a test table; it is preserved separately as an optional validation fixture. The catalog remains suitable for all products and services, including future hospitality use.

## Implemented foundation

NoETL YAML owns the database operations. The Rust PostgreSQL tool executes prepared, bound SQL with atomic statement transactions. The schema includes users/provider identities, categories and localized content, items, bundles, images, numeric attributes and localized attribute content. Versioned provisioning is repeatable; reset is a separate explicit validation-only playbook. No Python backend, Python mock server or mock-dependent booking workflow remains.

PostgreSQL RLS derives identity from a trusted mapping of the connection login, not a workload user ID. Providers manage their own catalog rows; customers see their own profiles; taxonomy/account linking require administrative authority. This is not yet connected to the public frontend or an identity-verifying gateway. Never expose the administrative credential through public execution routes.

## PostgreSQL version target

PostgreSQL 19 is the target, with local validation against the available 19 Beta 3 prerelease. The final 19.x release is the intended production baseline. Setup and tests enforce major version 19 and use a separate data directory. Earlier 17.11 results remain archived, not relabeled. See the [version policy and pinned build](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/docs/postgresql19.md).

## Validation and runtime requirements

On PostgreSQL 19beta3, the package passed **37 direct Rust-tool/database checks** and **21 full local Rust server → EHDB bus → Rust worker executions**, including expected terminal failures. The linked validation report and execution-ID artifact distinguish those levels and list the actual coverage. No live database or production deployment was modified.

The inspected server parser rejects PostgreSQL positional parameter arrays; the package includes a tested compatibility patch required for those executions. The independent smallint result decoding fix is [noetl/tools#104](https://github.com/noetl/tools/pull/104). The playbooks use JSON row projection as a compatible workaround while that fix is under review. Literal template syntax inside caller data is preserved by encoding the bound request between rendering stages.

## Database, objects and identity

PostgreSQL is the target because this model needs relational constraints, transactions, localized joins and ownership enforcement. Prices remain integer cents. GCS remains an optional provider for image/object URIs; uploads/IAM/lifecycle integration are not implemented. The source used Auth0; Firebase is optional, not assumed. Verified identity linking belongs behind a trusted gateway, and raw OAuth/API tokens are not copied into the schema or examples.

## Remaining work

Legacy trip/tour/car availability and pricing parity, trip/itinerary/order/invoice migration, hospitality inventory/holds/reservations, real payments/refunds/outbox, verified public identity integration, object storage and historical data import/reconciliation remain explicit gaps. Catalog search must not be presented as an availability or booking guarantee.

The [former hospitality starter](Hospitality-Platform) was retired because its tests only proved Python mocks. Its old code remains in Git history.

## Playbook index

All paths below are `adiona/v1/<name>` in the NoETL catalog. See the YAML for accepted request fields. The ordinary application catalog must exclude `reset` and the source test fixture. Upserts replace their listed fields; missing nullable fields become null. Reads/deletes of invisible targets return no rows.

| Playbook | Purpose |
|---|---|
| [attribute_upsert](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/attribute_upsert.yaml) | attribute upsert |
| [bundle_link](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/bundle_link.yaml) | bundle link |
| [bundle_type_upsert](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/bundle_type_upsert.yaml) | bundle type upsert |
| [bundle_unlink](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/bundle_unlink.yaml) | bundle unlink |
| [catalog_list](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/catalog_list.yaml) | catalog list |
| [category_delete](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/category_delete.yaml) | category delete |
| [category_filter_list](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/category_filter_list.yaml) | category filter list |
| [category_image_upsert](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/category_image_upsert.yaml) | category image upsert |
| [category_list](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/category_list.yaml) | category list |
| [category_parent_set](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/category_parent_set.yaml) | category parent set |
| [category_translation_upsert](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/category_translation_upsert.yaml) | category translation upsert |
| [category_type_parent_set](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/category_type_parent_set.yaml) | category type parent set |
| [category_type_translation_upsert](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/category_type_translation_upsert.yaml) | category type translation upsert |
| [category_type_upsert](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/category_type_upsert.yaml) | category type upsert |
| [category_upsert](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/category_upsert.yaml) | category upsert |
| [currency_list](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/currency_list.yaml) | currency list |
| [currency_upsert](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/currency_upsert.yaml) | currency upsert |
| [item_attribute_delete](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/item_attribute_delete.yaml) | item attribute delete |
| [item_attribute_translation_delete](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/item_attribute_translation_delete.yaml) | item attribute translation delete |
| [item_attribute_translation_upsert](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/item_attribute_translation_upsert.yaml) | item attribute translation upsert |
| [item_attribute_upsert](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/item_attribute_upsert.yaml) | item attribute upsert |
| [item_category_link](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/item_category_link.yaml) | item category link |
| [item_category_unlink](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/item_category_unlink.yaml) | item category unlink |
| [item_delete](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/item_delete.yaml) | item delete |
| [item_get](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/item_get.yaml) | item get |
| [item_image_delete](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/item_image_delete.yaml) | item image delete |
| [item_image_upsert](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/item_image_upsert.yaml) | item image upsert |
| [item_translation_delete](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/item_translation_delete.yaml) | item translation delete |
| [item_translation_upsert](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/item_translation_upsert.yaml) | item translation upsert |
| [item_update](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/item_update.yaml) | item update |
| [item_upsert](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/item_upsert.yaml) | item upsert |
| [language_list](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/language_list.yaml) | language list |
| [language_upsert](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/language_upsert.yaml) | language upsert |
| [provision](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/provision.yaml) | provision |
| [region_list](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/region_list.yaml) | region list |
| [reset](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/reset.yaml) | reset |
| [source_postgres_fixture](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/source_postgres_fixture.yaml) | source postgres fixture |
| [user_delete](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/user_delete.yaml) | user delete |
| [user_get](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/user_get.yaml) | user get |
| [user_identity_delete](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/user_identity_delete.yaml) | user identity delete |
| [user_identity_list](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/user_identity_list.yaml) | user identity list |
| [user_identity_upsert](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/user_identity_upsert.yaml) | user identity upsert |
| [user_profile_update](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/user_profile_update.yaml) | user profile update |
| [user_type_list](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/user_type_list.yaml) | user type list |
| [user_upsert](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/playbooks/user_upsert.yaml) | user upsert |
