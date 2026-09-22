# Hospitality foundation

The unverified Python mock backend, seven mock-dependent booking workflows, and invented reservation schema have been removed. Their mock-only test results are not evidence of a working NoETL backend.

Continue with [Adiona catalog and users](../adiona/README.md): MySQL-source definitions converted to PostgreSQL, with business operations in NoETL YAML and real database validation. The catalog supports products and services, not only lodging.

The [new hospitality extension](../adiona/docs/hospitality.md) implements individual room availability, flat-rate quotes, holds, staff confirmation/cancellation, check-in/out and expiry using real PostgreSQL 19 and NoETL Rust execution. Payments and refunds remain subsequent work. No live payment or property system is connected. The previous draft remains available in Git history.
