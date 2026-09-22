# Hospitality platform foundation

The Python mock starter and its seven mock-dependent booking workflows have been removed. They did not validate a real database-backed NoETL reservation system.

Continue with the [Adiona migration](Adiona-Migration), which converts Adiona's source MySQL catalog/user schema to PostgreSQL and implements operations in NoETL YAML using the Rust runtime. It preserves products and services beyond lodging.

[Implementation and setup](https://github.com/noetl/travel/tree/feat/hospitality-playbooks/adiona) · [Migration PR #125](https://github.com/noetl/travel/pull/125) · [Validation](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/adiona/docs/validation.md)

Inventory by date, quotes, holds, reservations, payments, refunds, notifications and channel synchronization remain subsequent work. No production booking workflow is enabled. Source mappings and unresolved legacy tour/car/trip rules are documented explicitly; the earlier mock test counts are not current validation evidence.
