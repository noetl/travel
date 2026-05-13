import { WidgetStubCard } from './WidgetStubCard';

export interface HotelCardProps {
  payload: unknown;
  variantId?: string;
}

export function HotelCard({ payload, variantId }: HotelCardProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="hotel_card" variantId={variantId} payload={payload} />;
}
