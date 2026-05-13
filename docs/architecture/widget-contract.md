# Widget Contract

Muno uses a closed catalogue of pre-templated widgets. The AI chooses from known templates and fills fields that the schema allows; it does not invent arbitrary UI.

## Envelope

Every widget crosses the agent-to-renderer boundary as:

```json
{
  "widget_type": "hotel_card",
  "variant": "compact",
  "payload": {},
  "ai_adjustments": {
    "emphasis": "best_value",
    "annotations": [],
    "conditional_fields": {}
  },
  "schema_version": 1
}
```

`_envelope.schema.json` validates this wrapper. Each template schema validates only the `payload` object.

## Closed Catalogue

The renderer only accepts the 23 widget types in `playbooks/widget-contract/`. Unknown widget types or invalid payloads fall back to `bot_text` with a natural-language explanation. The agent must always produce a short textual description alongside a widget so fallback remains graceful.

## Schema Versioning

Breaking payload changes bump `schema_version`. During a migration, the renderer keeps version N and N-1 implementations. Additive optional fields do not require a version bump.

## AI Adjustments

The AI can adjust within declared knobs: variant, emphasis, bounded annotations, and conditional flags. It cannot create fields outside the schema or compose layouts the catalogue does not describe.

## Type Generation

`npm run build` invokes `scripts/build_widget_contracts.sh`, which runs `json-schema-to-typescript` over `playbooks/widget-contract/*.schema.json` and writes `src/contracts/widgets.ts`. The generated file is committed for editor support; schemas remain the source of truth.
