import { WidgetStubCard } from './WidgetStubCard';

export interface HotelListProps {
  payload: unknown;
  variantId?: string;
}

export function HotelList({ payload, variantId }: HotelListProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="hotel_list" variantId={variantId} payload={payload} />;
}
