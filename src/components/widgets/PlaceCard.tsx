import { WidgetStubCard } from './WidgetStubCard';

export interface PlaceCardProps {
  payload: unknown;
  variantId?: string;
}

export function PlaceCard({ payload, variantId }: PlaceCardProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="place_card" variantId={variantId} payload={payload} />;
}
