import { WidgetStubCard } from './WidgetStubCard';

export interface PartyPickerProps {
  payload: unknown;
  variantId?: string;
}

export function PartyPicker({ payload, variantId }: PartyPickerProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="party_picker" variantId={variantId} payload={payload} />;
}
