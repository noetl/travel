import { WidgetStubCard } from './WidgetStubCard';

export interface ItinerarySummaryProps {
  payload: unknown;
  variantId?: string;
}

export function ItinerarySummary({ payload, variantId }: ItinerarySummaryProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="itinerary_summary" variantId={variantId} payload={payload} />;
}
