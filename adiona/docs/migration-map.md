# Source analysis and migration map

## Authority and scope

The source backend is a PHP Slim 3 application using PDO calls into MySQL stored procedures and lookup views. The source-of-truth business schema for this migration is the modular DDL under `adiona-datamodel/mysqldb`, as requested. The older monolithic `adiona-entity-attribute-value-model.sql` and `adiona-travel-model.sql` are design snapshots: they contain overlapping/contradictory table definitions and a different generic entities/attribute_content model. They are not concatenated into a pretend runnable schema.

The supplied `adiona/database/postgres/schema_ddl.sql` contains only `test_data_table`, synthetic inserts, psql variable substitution, and an unused `plpython3u` extension declaration. It does not implement users, items, catalog or reservations. Its table is preserved as an optional isolated fixture; business provisioning is a MySQL-to-PostgreSQL port. No PL/Python is used.

This is a catalog/user foundation, not a complete recreation of all travel/payment endpoints. Every unsupported endpoint remains listed below. No historical customer records or source seed files are published or imported.

## Entity and dependency map

| MySQL modular source | Target and behavior |
|---|---|
| `languages/languages.ddl.sql` | `languages`; language code, display name, supported/image metadata |
| `currencies/carrencies.ddl.sql` | `currencies`, `currency_history`; exchange-rate storage, no automatic FX refresh |
| `users/users.ddl.sql` | `user_type` before `users` before `user_auth`; profile fields, per-email/type uniqueness, subject linkage |
| `users/auth0/auth0.ddl.sql` | Legacy unkeyed token/profile staging table intentionally not reproduced; stable subject linkage in `user_auth` |
| `categories/category_types.ddl.sql` | `category_types`; self-parent relationship and unique type |
| `categories/category_type_content.ddl.sql` | Localized type content, one value per type/language |
| `categories/categories.ddl.sql` | `categories`, `category_images`; type relationship, parent relationship, source name/language/type key |
| `categories/category_content.ddl.sql` | Localized category content; one current value per category/language |
| `items/items_ddl.sql` | `items`, `bundle_type`, `items_bundle`, `item_content`, `item_category`, `item_images`; provider, cents price, localized content, many-to-many links and reusable product/service bundles |
| `attributes/attributes.ddl.sql` | `attributes`, `item_attributes`, `item_attribute_content`; numeric attribute values and language-specific text |
| Same attributes file: trip variants | Deferred with the trip aggregate, not silently redirected into item attributes |
| `trips/trips.ddl.sql` | Trip durations/content/categories/images are analyzed but not provisioned; itinerary and departure schedules require a separate domain migration |
| `itinerary/itinerary.ddl.sql` | Day-level itinerary/item composition deferred with trips |
| `orders/orders.ddl.sql` | Order/header/line/customer/payment dependencies deferred; no payment workflow is represented as complete |
| `labels/**`, `utilities/**` | UI dictionaries, label hierarchy, bank/reference utilities deferred |

Dependency order is languages/currencies → user types/users → category types/categories → items → localized content and associations → attributes and values. Foreign keys are never globally disabled. There is no lodging-only replacement model.

## Important conversion differences

| Source behavior/problem | PostgreSQL decision |
|---|---|
| `AUTO_INCREMENT`, `BIGINT(20)`, `TINYINT` | Identity columns; bigint IDs and cents; smallint flags/type IDs; display widths removed |
| MySQL `USE`, backticks, `ENGINE`, `CHARSET`, `FOREIGN_KEY_CHECKS=0`, destructive DROP-first scripts | Fixed qualified `adiona` schema, UTF-8 target, ordered FK creation, transactional version ledger; no implicit reset |
| Procedure lookup then INSERT/UPDATE races | Explicit natural-key constraints and `ON CONFLICT` in one bound statement |
| Item identity lookup `(language,name)` could collide across providers | `(provider_id,default_lang_code,item_name)`; preserves retries while separating owners. An intentional stronger identity contract |
| `item_content` procedure assumes one row per item/language but DDL lacks it | Unique `(item_id,lang_code)`; nonnull slug unique within language |
| Category-content modular unique includes translated value, allowing duplicates per language; other snapshot uses only category/language | Unique `(category_id,lang_code)` consistent with replacement/upsert semantics; legacy duplicates need reconciliation before import |
| MySQL default collation may compare catalog names case-insensitively; source files do not pin a consistent collation | PostgreSQL catalog names/slugs use exact case-sensitive keys. Email is normalized to lowercase. Historical case/accent collisions require an explicit import reconciliation decision; byte-for-byte collation parity is not claimed |
| Provider, parent-category and attribute-category relationships incompletely constrained | Explicit FKs; parent self-reference CHECK; playbook graph updates reject cycles at SERIALIZABLE isolation |
| Bundle relationship parent ID incorrectly auto-increments while also referencing items | Explicit existing bundle item ID; no independent sequence |
| Mutable creation timestamp and MySQL `ON UPDATE CURRENT_TIMESTAMP` | Stable `created_dtm`; PostgreSQL timestamps with zone; user security trigger updates `modified_dtm` |
| MySQL currency FLOAT | Exact `numeric(24,10)`; cents prices remain bigint; no inferred currency conversion or tax policy |
| Default timezone `PST` | `UTC` default; existing users' timezone strings are preserved on explicit import |
| Missing/nullable emails, lax flags and negative prices | Required syntactically valid email for managed users, normalized email/currency/language, nonnegative price and checked flags. These are deliberate validation changes |
| Raw OAuth access/refresh tokens and generated API tokens in source user storage | Opaque credential reference only; no raw-token database fields, logs, examples or migration |
| Auth0 snapshot has no primary/unique key despite ON DUPLICATE KEY UPDATE | Provider subject uniqueness `(method,id)` prevents attaching one external subject to two users |
| Arbitrary/weak backend authentication boundaries | DB session-bound principals, RLS, admin-only taxonomy/account linking; public gateway binding deferred |
| `CALL` with OUT/session variables and multiple PDO commands | Single-statement YAML operations return typed JSON result rows; no session-variable state across pooled connections |
| `GROUP_CONCAT`, `IFNULL`, `STR_TO_DATE`, MySQL aggregation/availability procedures | Generic catalog uses relational joins and JSON aggregation. Specialized tour/car/trip views are not falsely presented as converted |

Migration/import must separately resolve duplicate translations, duplicate natural keys, dangling provider/category references, invalid email/currency references, cyclic parent graphs, ambiguous slugs and legacy timestamps. The source schema cannot safely be bulk-loaded unchanged under the stronger constraints. This package does not claim live data migration or source/target row reconciliation.

## Backend endpoint → playbook map

Paths are relative to `/v1` unless stated otherwise. Mapped operations are application building blocks, not an HTTP compatibility server.

| Source route(s) | Source controller / database operation | Migration status |
|---|---|---|
| `GET /user` | `UserController.index` returns a controller string | Useful replacement `user_get`; legacy response intentionally not reproduced |
| `POST /user` | `addUser` calls `upload_auth0`; accepts profile/provider fields and returns generated API token | `user_upsert`, `user_identity_upsert`; administrator/verified gateway only. `upload_auth0` definition is missing from supplied datamodel (which instead defines `upsert_auth0`) |
| `POST /user/verify` | Auth0 JWTVerifier, RS256, audience/issuer | Gateway authentication gap; do not replace verification with a supplied actor ID or trust submitted `email_verified` |
| `POST /tours`, `POST /tour` | `get_tours(region,price_min,price_max,start_date,end_date,adults,children,lang)` | Generic item filtering available in `catalog_list`; tour date/capacity/pricing semantics remain deferred |
| `GET /tour/{id}/{date}/{lang}` | `get_tour_details(slug,date,lang)` | `item_get` provides catalog data; exact tour detail envelope/pricing deferred |
| `GET /trips/category/{id}/{lang}` | `TripsController.getTripsForCategory` | Trip-specific category query deferred |
| `POST /trip` | `get_trips` | Trip search deferred |
| `GET /trip/{id}/{date}/{lang}` | `get_trip_details` and related lookup content | Trip aggregate deferred |
| `GET /trip/tripdetails` | `getTripDetails` | Incomplete/ambiguous source route versus parameterized detail route; deferred |
| `POST /trip/order` | Route names `TripsController::class . 'submitOrder'` without `:` | Source routing defect; not silently implemented as a working order API |
| `POST /cars` | `get_cars` filters location, attributes, dates, capacity and prices | Generic catalog preserves attribute/category storage; car availability/FX/response parity deferred |
| `GET /cars/{id}/{lang}` | `get_car_details` | Generic `item_get`; exact car detail payload deferred |
| `GET /lang/all[/{active}]` | Language support filter | `language_list`; request uses explicit `supported` Y/N |
| `POST /lang/translit/{lang}` | Transliteration utility | Deferred; no speculative transliteration rule |
| `GET /lang/dictionary/{lang}`, `GET /lang/{type}/{lang}` | Label/dictionary lookups | Deferred with labels aggregate |
| `GET /currency`, `GET /exchange` | Currency/exchange views | `currency_list`, `currency_upsert`; legacy display/FX response contract and refresh deferred |
| `GET /category/region/{lang}` | `categories_lookup` restricted to region/country | `region_list` |
| `GET /category/{type}/{lang}` | `get_categories` → `categories_filter_lookup` | `category_filter_list` preserves trips→trip_category, tours→tour_category, cars→car_type, localized labels and main image; `category_list` is general taxonomy lookup |
| `GET /order/all`, `/order/all/email/{email}`, `/order/all/id/{user_id}`, `/order/id/{order_id}` | OrdersController order/customer detail reads | Deferred; must add owner/staff authorization before exposure |
| `POST /order`, `PUT /order` | PaymentController order mutations | Deferred with order aggregate, currency and payment contracts |
| `POST /payment/create`, GET/POST `/payment/success`, GET/POST `/payment/fail` | Provider payment/callback handling | Deferred; no provider writes, simulated capture or unverified callbacks |
| `POST /feedback/form` | Feedback delivery | Deferred; no email/message is sent |
| Root `/callback`, `/mailgun`, `/` | Debug callback, mail provider test, home page | Not migrated; debug/provider test routes must not become public backend operations |

Additional administrative source procedures map to `item_upsert`, `item_translation_upsert`, `item_category_link`, `item_image_upsert`, `item_attribute_upsert`, `item_attribute_translation_upsert`, category/type translation upserts and user identity upserts. Corresponding explicit unlink/delete playbooks support controlled cleanup. These procedures were not exposed as separate CRUD routes in the PHP backend; the playbooks add a controlled operational surface.

Source `upsert_users_proc` calls `insert_user_type_proc`/`insert_user_auth_proc` while modular files define `upsert_*`; this naming drift and the missing `upload_auth0` mean the source itself is not a clean executable specification. `check_user_auth_func` counts rows; it is not credential verification. Backend bootstrap middleware handles errors/CORS but does not establish a consistent endpoint-level principal boundary. Migration tightens these boundaries rather than reproducing weak source behavior.

## Specialized rules retained as explicit gaps

`get_tours` filters region, inclusive minimum/maximum price, available-from ≤ requested start, available-till ≥ requested end, separate adult/child limits and combined seat capacity; language defaults to English. Its result computes the next tour start from the day-of-week helper and includes child price and discount. Currency-conversion calls are commented out in that procedure. Generic `catalog_list` implements only catalog price/category/language filtering, and must not be advertised as validating availability or capacity.

`get_cars` parses long age strings from their first two characters, filters minimum driver age and date boundaries, and returns car-specific attributes and image variants. Its currency conversion is also commented out. These unusual legacy semantics need an explicit compatibility decision before public car search is migrated.

Order definitions have status lookup tables, customer order headers/lines and invoices, but several intended provider/trip/item links are indexes or unconstrained IDs instead of FKs. Itineraries link trips and items with unique `(trip_id,item_id,event_day,event_order)` and separate localized day content. Their incomplete source constraints are a reason for a separately reviewed domain migration, not a reason to assume reservation correctness from catalog CRUD.
