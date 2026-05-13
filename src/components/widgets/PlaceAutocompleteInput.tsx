import { WidgetStubCard } from './WidgetStubCard';

export interface PlaceAutocompleteInputProps {
  payload: unknown;
  variantId?: string;
}

export function PlaceAutocompleteInput({ payload, variantId }: PlaceAutocompleteInputProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="place_autocomplete_input" variantId={variantId} payload={payload} />;
}
