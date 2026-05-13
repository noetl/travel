import { WidgetStubCard } from './WidgetStubCard';

export interface FlightListProps {
  payload: unknown;
  variantId?: string;
}

export function FlightList({ payload, variantId }: FlightListProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="flight_list" variantId={variantId} payload={payload} />;
}
