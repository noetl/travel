import Ajv, { type AnySchema, type ValidateFunction } from 'ajv';
import addFormats from 'ajv-formats';
import { Alert } from '@mui/material';
import type React from 'react';
import envelopeSchema from '../../playbooks/widget-contract/_envelope.schema.json';
import bot_textSchema from '../../playbooks/widget-contract/bot_text.schema.json';
import user_textSchema from '../../playbooks/widget-contract/user_text.schema.json';
import typing_indicatorSchema from '../../playbooks/widget-contract/typing_indicator.schema.json';
import date_range_pickerSchema from '../../playbooks/widget-contract/date_range_picker.schema.json';
import party_pickerSchema from '../../playbooks/widget-contract/party_picker.schema.json';
import place_autocomplete_inputSchema from '../../playbooks/widget-contract/place_autocomplete_input.schema.json';
import flight_listSchema from '../../playbooks/widget-contract/flight_list.schema.json';
import flight_cardSchema from '../../playbooks/widget-contract/flight_card.schema.json';
import hotel_listSchema from '../../playbooks/widget-contract/hotel_list.schema.json';
import hotel_cardSchema from '../../playbooks/widget-contract/hotel_card.schema.json';
import hotel_compareSchema from '../../playbooks/widget-contract/hotel_compare.schema.json';
import place_listSchema from '../../playbooks/widget-contract/place_list.schema.json';
import place_cardSchema from '../../playbooks/widget-contract/place_card.schema.json';
import action_chooserSchema from '../../playbooks/widget-contract/action_chooser.schema.json';
import map_viewSchema from '../../playbooks/widget-contract/map_view.schema.json';
import filter_panelSchema from '../../playbooks/widget-contract/filter_panel.schema.json';
import property_blockSchema from '../../playbooks/widget-contract/property_block.schema.json';
import itinerary_summarySchema from '../../playbooks/widget-contract/itinerary_summary.schema.json';
import order_confirmationSchema from '../../playbooks/widget-contract/order_confirmation.schema.json';
import notificationSchema from '../../playbooks/widget-contract/notification.schema.json';
import error_cardSchema from '../../playbooks/widget-contract/error_card.schema.json';
import clarify_questionSchema from '../../playbooks/widget-contract/clarify_question.schema.json';
import loading_cardSchema from '../../playbooks/widget-contract/loading_card.schema.json';
import { BotText } from './widgets/BotText';
import { UserText } from './widgets/UserText';
import { TypingIndicator } from './widgets/TypingIndicator';
import { DateRangePicker } from './widgets/DateRangePicker';
import { PartyPicker } from './widgets/PartyPicker';
import { PlaceAutocompleteInput } from './widgets/PlaceAutocompleteInput';
import { FlightList } from './widgets/FlightList';
import { FlightCard } from './widgets/FlightCard';
import { HotelList } from './widgets/HotelList';
import { HotelCard } from './widgets/HotelCard';
import { HotelCompare } from './widgets/HotelCompare';
import { PlaceList } from './widgets/PlaceList';
import { PlaceCard } from './widgets/PlaceCard';
import { ActionChooser } from './widgets/ActionChooser';
import { MapView } from './widgets/MapView';
import { FilterPanel } from './widgets/FilterPanel';
import { PropertyBlock } from './widgets/PropertyBlock';
import { ItinerarySummary } from './widgets/ItinerarySummary';
import { OrderConfirmation } from './widgets/OrderConfirmation';
import { Notification } from './widgets/Notification';
import { ErrorCard } from './widgets/ErrorCard';
import { ClarifyQuestion } from './widgets/ClarifyQuestion';
import { LoadingCard } from './widgets/LoadingCard';

export interface WidgetRendererProps {
  envelope: unknown;
}

const ajv = new Ajv({ allErrors: true, strict: false });
addFormats(ajv);
const envelopeValidator = ajv.compile(envelopeSchema);
const payloadSchemas: Record<string, AnySchema> = {
  bot_text: bot_textSchema,
  user_text: user_textSchema,
  typing_indicator: typing_indicatorSchema,
  date_range_picker: date_range_pickerSchema,
  party_picker: party_pickerSchema,
  place_autocomplete_input: place_autocomplete_inputSchema,
  flight_list: flight_listSchema,
  flight_card: flight_cardSchema,
  hotel_list: hotel_listSchema,
  hotel_card: hotel_cardSchema,
  hotel_compare: hotel_compareSchema,
  place_list: place_listSchema,
  place_card: place_cardSchema,
  action_chooser: action_chooserSchema,
  map_view: map_viewSchema,
  filter_panel: filter_panelSchema,
  property_block: property_blockSchema,
  itinerary_summary: itinerary_summarySchema,
  order_confirmation: order_confirmationSchema,
  notification: notificationSchema,
  error_card: error_cardSchema,
  clarify_question: clarify_questionSchema,
  loading_card: loading_cardSchema
};
Object.values(payloadSchemas).forEach((schema) => ajv.addSchema(schema));
const schemaValidators: Record<string, ValidateFunction> = Object.fromEntries(
  Object.entries(payloadSchemas).map(([name, schema]) => [name, ajv.compile(schema)])
);
const componentMap: Record<string, React.ComponentType<{ payload: unknown; variantId?: string }>> = {
  bot_text: BotText,
  user_text: UserText,
  typing_indicator: TypingIndicator,
  date_range_picker: DateRangePicker,
  party_picker: PartyPicker,
  place_autocomplete_input: PlaceAutocompleteInput,
  flight_list: FlightList,
  flight_card: FlightCard,
  hotel_list: HotelList,
  hotel_card: HotelCard,
  hotel_compare: HotelCompare,
  place_list: PlaceList,
  place_card: PlaceCard,
  action_chooser: ActionChooser,
  map_view: MapView,
  filter_panel: FilterPanel,
  property_block: PropertyBlock,
  itinerary_summary: ItinerarySummary,
  order_confirmation: OrderConfirmation,
  notification: Notification,
  error_card: ErrorCard,
  clarify_question: ClarifyQuestion,
  loading_card: LoadingCard
};

function fallbackText(reason: string) {
  return { text: `Unable to render this response (template mismatch): ${reason}`, markdown: false };
}

export function WidgetRenderer({ envelope }: WidgetRendererProps) {
  if (!envelopeValidator(envelope)) {
    return <BotText payload={fallbackText(ajv.errorsText(envelopeValidator.errors))} variantId="default" />;
  }
  const wire = envelope as { widget_type: string; variant: string; payload: unknown; schema_version: number };
  const payloadValidator = schemaValidators[wire.widget_type];
  const Component = componentMap[wire.widget_type];
  if (!payloadValidator || !Component) {
    return <BotText payload={fallbackText(`unknown widget_type ${wire.widget_type}`)} variantId="default" />;
  }
  if (!payloadValidator(wire.payload)) {
    return <BotText payload={fallbackText(ajv.errorsText(payloadValidator.errors))} variantId="default" />;
  }
  if (wire.schema_version !== 1) {
    return <Alert severity="warning">Unsupported widget schema version: {wire.schema_version}</Alert>;
  }
  return <Component payload={wire.payload} variantId={wire.variant} />;
}
