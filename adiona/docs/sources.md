# Inspected source revisions

Private source repositories require their own access. Only adapted definitions and analysis belong in the destination; no source seeds or secrets are included.

| Repository | Commit |
|---|---|
| [adiona/adiona-backend](https://github.com/adiona/adiona-backend/tree/bcbfa3c9ff2d581249d1b90098f284e57c6435ec) | `bcbfa3c9ff2d581249d1b90098f284e57c6435ec` |
| [adiona/adiona](https://github.com/adiona/adiona/tree/d12c0af490272dc3bf184bbc5483f8d3c5895d15) | `d12c0af490272dc3bf184bbc5483f8d3c5895d15` |
| [adiona/adiona-datamodel](https://github.com/adiona/adiona-datamodel/tree/9a4bdbbff0de411f0cb132af0584491874659d75) | `9a4bdbbff0de411f0cb132af0584491874659d75` |
| [noetl/noetl](https://github.com/noetl/noetl/tree/0a01c0df2d2a7d8bf66e0d553124e20928282f2c) | `0a01c0df2d2a7d8bf66e0d553124e20928282f2c` |
| [noetl/tools](https://github.com/noetl/tools/tree/e66e49c27a3d9022c5bf5cab98423f13fbe5bc88) | `e66e49c27a3d9022c5bf5cab98423f13fbe5bc88` |
| [noetl/server](https://github.com/noetl/server/tree/35c451825106ff7e5723bcaa14935f1dca88a9cc) | `35c451825106ff7e5723bcaa14935f1dca88a9cc` |
| [noetl/worker](https://github.com/noetl/worker/tree/7bce66c6a1486ccf73d1de698431a179c6646c90) | `7bce66c6a1486ccf73d1de698431a179c6646c90` |
| [noetl/cli](https://github.com/noetl/cli/tree/8b1e6ae7152dab2f6f2f30c8d9a6d4abe2ef5503) | `8b1e6ae7152dab2f6f2f30c8d9a6d4abe2ef5503` |
| [noetl/e2e](https://github.com/noetl/e2e/tree/1e41859c90069e63e3884fdc7555beced19deeda) | `1e41859c90069e63e3884fdc7555beced19deeda` |

## Syntax and implementation references

- `noetl/tools/src/tools/postgres.rs`: `command` alias, positional `params`, prepared query execution, JSON conversion, pool behavior.
- `noetl/tools/src/template/engine.rs`: Jinja value rendering and `tojson` support.
- `noetl/worker/src/executor/auth_alias.rs`: credential alias resolution and PostgreSQL credential fields.
- `noetl/server/orchestrate-core/src/playbook.rs`: single-tool DSL, explicit start step, parser incompatibility with positional parameters (bundled patch).
- `noetl/e2e/fixtures/playbooks/data_transfer/postgres_jsonb_test/postgres_jsonb_test.yaml`: current `noetl.io/v2`, `kind: postgres`, `auth`, `command` examples. Its Python steps and interpolated SQL were not copied.
- `noetl/cli/src/playbook_runner.rs`: local mode does not dispatch PostgreSQL; use distributed Rust server/worker, not a successful-looking local CLI run.

## Modular SQL object inventory

Names below are extracted from CREATE definitions, not seed records or source bodies. Multiple declarations reflect divergent historical snapshots. This inventory establishes analyzed dependencies; it does not imply every object has been ported.

| File | Declared SQL objects |
|---|---|
| `adiona-entity-attribute-value-model.sql` | table languages, table currencies, table currency_history, table entities, procedure insert_entities_proc, table attributes, procedure insert_attribute_proc, table attribute_content, procedure merge_attribute_content_proc, table category_types, table category_type_content, procedure insert_category_types_proc, table categories, table category_content, procedure insert_categories_proc, table trips, table trip_category |
| `adiona-travel-model.sql` | table languages, table currencies, table currency_history, table category_types, function get_category_type_id_func, table category_type_content, procedure insert_category_type_content_proc, procedure update_category_type_content_proc, procedure insert_category_types_proc, table categories, table category_content, procedure insert_category_content_proc, procedure insert_categories_proc, table entities, procedure insert_entities_proc, table attributes, procedure insert_attribute_proc, table attribute_content, procedure merge_attribute_content_proc, table trips, table trip_content, table trip_category |
| `attributes/attributes.ddl.sql` | table attributes, table item_attributes, table item_attribute_content, table trip_attributes, table trip_attribute_content |
| `attributes/attributes_lookup.sql` | view attributes_lookup |
| `attributes/get_attribute_id_func.sql` | function get_attribute_id_func |
| `attributes/insert_attribute_proc.sql` | procedure insert_attribute_proc |
| `attributes/insert_item_attribute_content_proc.sql` | procedure insert_item_attribute_content_proc |
| `attributes/insert_item_attribute_proc.sql` | procedure insert_item_attribute_proc |
| `attributes/insert_trip_attribute_content_proc.sql` | procedure insert_trip_attribute_content_proc |
| `attributes/insert_trip_attribute_proc.sql` | procedure insert_trip_attribute_proc |
| `cars/cars_lookup.sql` | view cars_lookup |
| `cars/get_cars.sql` | procedure get_cars |
| `categories/categories.ddl.sql` | table categories, table category_images |
| `categories/categories_filter_lookup.sql` | view categories_filter_lookup |
| `categories/categories_lookup.ddl.sql` | view categories_lookup |
| `categories/category_content.ddl.sql` | table category_content |
| `categories/category_type_content.ddl.sql` | table category_type_content |
| `categories/category_types.ddl.sql` | table category_types |
| `categories/get_categories.sql` | procedure get_categories |
| `categories/get_category_id_func.ddl.sql` | function get_category_id_func |
| `categories/get_category_type_id_func.ddl.sql` | function get_category_type_id_func |
| `categories/insert_category_content_proc.ddl.sql` | procedure insert_category_content_proc |
| `categories/insert_category_image_proc.sql` | procedure insert_category_image_proc |
| `categories/insert_category_proc.ddl.sql` | procedure insert_category_proc |
| `categories/insert_category_type_content_proc.ddl.sql` | procedure insert_category_type_content_proc |
| `categories/insert_category_types_proc.ddl.sql` | procedure insert_category_types_proc |
| `categories/update_category_type_content_proc.ddl.sql` | procedure update_category_type_content_proc |
| `create-trip-database.sql` | table user_type, procedure insert_user_type_proc, table users, table user_auth, procedure insert_user_auth_proc, procedure insert_users_proc, function check_user_auth_func, table languages, table currencies, table currency_history, table label_types, function get_label_type_id_func, table label_type_content, procedure insert_label_type_content_proc, procedure update_label_type_content_proc, procedure insert_label_types_proc, table labels, table label_content, function get_label_id_func, procedure insert_label_content_proc, procedure insert_labels_proc, view labels_lookup, view menu, view web_pages, view filters, view filter_tabs, view filter_buttons, view filter_fields, table category_types, function get_category_type_id_func, table category_type_content, procedure insert_category_type_content_proc, procedure update_category_type_content_proc, procedure insert_category_types_proc, table categories, table category_content, function get_category_id_func, procedure insert_category_content_proc, procedure insert_categories_proc, view categories_lookup, table trips, table trip_content, table trip_category, table trip_images, function get_trip_id_func, procedure insert_trip_content_proc, procedure update_trip_content_proc, procedure insert_trip_proc, procedure insert_trip_category_proc, procedure insert_trip_image_proc, view trip_lookup |
| `currencies/carrencies.ddl.sql` | table currencies, table currency_history |
| `currencies/currencies_lookup.sql` | view currencies_lookup |
| `items/get_item_id_from_slug_func.sql` | function get_item_id_from_slug_func |
| `items/get_item_id_func.sql` | function get_item_id_func |
| `items/insert_item_category_proc.sql` | procedure insert_item_category_proc |
| `items/insert_item_content_proc.sql` | procedure insert_item_content_proc |
| `items/insert_item_image_proc.sql` | procedure insert_item_image_proc |
| `items/insert_item_proc.sql` | procedure insert_item_proc |
| `items/item_images_lookup.sql` | view item_images_lookup |
| `items/item_region_lookup.sql` | view item_region_lookup |
| `items/item_week_lookup.sql` | view item_week_lookup |
| `items/items_attributes_lookup.sql` | view items_attributes_lookup |
| `items/items_ddl.sql` | table items, table bundle_type, table items_bundle, table item_content, table item_category, table item_images |
| `items/items_lookup.sql` | view items_lookup |
| `items/update_item_content_proc.sql` | procedure update_item_content_proc |
| `itinerary/insert_itinerary_content_day_proc.sql` | procedure insert_itinerary_content_day_proc |
| `itinerary/insert_itinerary_item_proc.sql` | procedure insert_itinerary_item_proc |
| `itinerary/itineraries_lookup.sql` | view itineraries_lookup |
| `itinerary/itinerary.ddl.sql` | table itineraries, table itinerary_day_content |
| `labels/get_dictionary_proc.sql` | procedure get_dictionary_proc |
| `labels/get_label_id_func.ddl.sql` | function get_label_id_func |
| `labels/get_label_type_id_func.ddl.sql` | function get_label_type_id_func |
| `labels/header/header_currencies_label.ddl.sql` | view header_currencies_label |
| `labels/header/header_filter_buttons_label.ddl.sql` | view header_filter_buttons_label |
| `labels/header/header_filter_fields_label.ddl.sql` | view header_filter_fields_label |
| `labels/header/header_filter_tabs_label.ddl.sql` | view header_filter_tabs_label |
| `labels/header/header_languages_label.ddl.sql` | view header_languages_label |
| `labels/header/header_menu_items_label.ddl.sql` | view header_menu_items_label |
| `labels/insert_label_content_proc.ddl.sql` | procedure insert_label_content_proc |
| `labels/insert_label_type_content_proc.ddl.sql` | procedure insert_label_type_content_proc |
| `labels/insert_label_types_proc.ddl.sql` | procedure insert_label_types_proc |
| `labels/insert_labels_proc.ddl.sql` | procedure insert_labels_proc |
| `labels/label_content.ddl.sql` | table label_content |
| `labels/label_type_content.ddl.sql` | table label_type_content |
| `labels/label_types.ddl.sql` | table label_types |
| `labels/label_types_hierarchy.ddl.sql` | view label_types_hierarchy |
| `labels/labels.ddl.sql` | table labels |
| `labels/labels_lookup.ddl.sql` | view labels_lookup |
| `labels/update_label_type_content_proc.ddl.sql` | procedure update_label_type_content_proc |
| `labels/web-pages/main_page_trips_trip_category_labels.sql` | view main_page_trips_trip_category_labels |
| `labels/web-pages/web_pages_lookup.ddl.sql` | view web_pages_lookup |
| `languages/language_lookup.sql` | view language_lookup |
| `languages/languages.ddl.sql` | table languages |
| `orders/customer_order_line_status.sql` | view customer_order_line_status_lookup |
| `orders/customer_order_status_lookup.sql` | view customer_order_status_lookup |
| `orders/customer_order_tables.sql` | table customer_order, table customer_order_line, table invoice, table customer_order_travel_document |
| `orders/get_customer_order.sql` | procedure get_customer_order |
| `orders/orders.ddl.sql` | table customer_order_status_lookup, table customer_order_line_status_lookup, table invoice_status_lookup, table customer_order, table customer_order_line, table invoice |
| `orders/test.sql` | table customer_order_status_lookup, table customer_order_line_status_lookup, table invoice_status_lookup, table customer_order, table customer_order_line, table invoice, table travel_document, table customer_order_travel_document |
| `orders/upsert_customer_order.sql` | procedure upsert_customer_order |
| `temp.sql` | table languages, table currencies, table currency_history, table user_type, table user_type_translate, table item_type, table item_type_translate, table users, table user_translate, table user_auth, table discount_option, table discount_option_translate, table location, table location_translate, table item, table item_translate, table item_discount, table item_discount_translate, table trip_category_type, table trip_type_translate, table trip, table trip_translate, table trip_discount, table trip_discount_translate, table attribute, table attribute_translate, table item_attribute_value, table item_attribute_value_translate, table item_bundle, table itinerary, table itinerary_translate, table image_url, table order_status, table order_status_translate, table order_line_status, table order_line_status_translate, table customer_order, table customer_order_translate, table customer_order_line, table customer_itinerary_detail, table customer_itinerary_detail_translate, table invoice, table invoice_translate, table category_types, function get_category_type_id_func, table category_type_content, procedure insert_category_type_content_proc, procedure update_category_type_content_proc, procedure insert_category_types_proc, table categories, table category_content, function get_category_id_func, procedure insert_category_content_proc, procedure insert_categories_proc, view categories_lookup, view menu, view web_pages, view filters, view filter_tabs, view filter_buttons, view filter_fields |
| `tours/tours_lookup.sql` | view tours_lookup |
| `trips/delete_trip_proc.sql` | procedure delete_trip_proc |
| `trips/get_trip_header.sql` | procedure get_trip_header |
| `trips/get_trip_id_from_slug_func.sql` | function get_trip_id_from_slug_func |
| `trips/get_trip_id_func.sql` | function get_trip_id_func |
| `trips/insert_trip_category_proc.sql` | procedure insert_trip_category_proc |
| `trips/insert_trip_content_proc.sql` | procedure insert_trip_content_proc |
| `trips/insert_trip_image_proc.sql` | procedure insert_trip_image_proc |
| `trips/insert_trip_proc.sql` | procedure insert_trip_proc |
| `trips/trip_category_lookup.sql` | view trip_category_lookup |
| `trips/trip_region_lookup.sql` | view trip_region_lookup |
| `trips/trip_type_lookup.sql` | view trip_type_lookup |
| `trips/trip_week_lookup.sql` | view trip_week_lookup |
| `trips/trips.ddl.sql` | table trips, table trip_content, table trip_category, table trip_images |
| `trips/trips_attributes_lookup.sql` | view trips_attributes_lookup |
| `trips/trips_lookup.sql` | view trips_lookup |
| `trips/update_trip_content_proc.sql` | procedure update_trip_content_proc |
| `users/auth0/auth0.ddl.sql` | table auth0 |
| `users/auth0/get-auth0-proc.sql` | procedure get_auth0 |
| `users/auth0/upsert-auth0-proc.sql` | procedure upsert_auth0 |
| `users/check_user_auth_func.sql` | function check_user_auth_func |
| `users/upsert_user_auth_proc.sql` | procedure upsert_user_auth_proc |
| `users/upsert_user_type_proc.sql` | procedure upsert_user_type_proc |
| `users/upsert_users_proc.sql` | procedure upsert_users_proc |
| `users/users.ddl.sql` | table users, table user_auth, table user_type |
| `utilities/bank_codes.ddl.sql` | table bank_codes |
| `utilities/get_default_lang_code_func.sql` | function get_default_lang_code_func |
| `utilities/slug.sql` | function slugify |
| `utilities/split_str.sql` | function SPLIT_STR |
| `utilities/transliterate_ru.sql` | function transliterate_ru |
