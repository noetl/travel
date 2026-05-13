import { WidgetStubCard } from './WidgetStubCard';

export interface HotelCompareProps {
  payload: unknown;
  variantId?: string;
}

export function HotelCompare({ payload, variantId }: HotelCompareProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="hotel_compare" variantId={variantId} payload={payload} />;
}
