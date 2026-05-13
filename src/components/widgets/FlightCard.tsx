import { WidgetStubCard } from './WidgetStubCard';

export interface FlightCardProps {
  payload: unknown;
  variantId?: string;
}

export function FlightCard({ payload, variantId }: FlightCardProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="flight_card" variantId={variantId} payload={payload} />;
}
