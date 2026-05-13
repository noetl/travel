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

`npm run build` invokes `scripts/generate_widget_contracts.mjs`, which runs `json-schema-to-typescript` over `playbooks/widget-contract/*.schema.json` and writes `src/contracts/widgets.ts`. The generated file is committed for editor support; schemas remain the source of truth.

## Material Implementation Notes

Round 6b replaced the JSON stubs with real Material UI v6 components under
`src/components/widgets/`. Each schema maps one-to-one to a component and is
still validated before render by `WidgetRenderer`.

| Widget type | Component | Notes |
| --- | --- | --- |
| `bot_text` | `BotText` | Markdown-capable Adiona bubble. |
| `user_text` | `UserText` | Right-aligned user bubble. |
| `typing_indicator` | `TypingIndicator` | Animated dot row. |
| `clarify_question` | `ClarifyQuestion` | Chip-based choices. |
| `date_range_picker` | `DateRangePicker` | Native date inputs with computed nights. |
| `party_picker` | `PartyPicker` | Steppers plus child-age selects. |
| `place_autocomplete_input` | `PlaceAutocompleteInput` | Free-solo MUI autocomplete. |
| `action_chooser` | `ActionChooser` | Illustrated CTA cards. |
| `flight_card` / `flight_list` | `FlightCard`, `FlightList` | Compact/full/in-popover offer display. |
| `hotel_card` / `hotel_list` / `hotel_compare` | `HotelCard`, `HotelList`, `HotelCompare` | Card variants, compare grid, upsell banner. |
| `place_card` / `place_list` | `PlaceCard`, `PlaceList` | Destination grid cards. |
| `map_view` | `MapView` | Google Maps JS via `VITE_GOOGLE_MAPS_KEY`, with a no-key preview fallback. |
| `filter_panel` | `FilterPanel` | Right-pane filter controls. |
| `property_block` | `PropertyBlock` | Slot accumulator with edit actions. |
| `itinerary_summary` | `ItinerarySummary` | End-of-flow review. |
| `order_confirmation` | `OrderConfirmation` | Test-order receipt. |
| `loading_card`, `error_card`, `notification` | `LoadingCard`, `ErrorCard`, `Notification` | Lifecycle states. |

Interactive components emit `widget_submit` or `widget_cta_click` through the
optional `WidgetRenderer.onWidgetEvent` callback. Surfaces that do not pass a
callback still render safely.
