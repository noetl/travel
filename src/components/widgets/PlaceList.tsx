import { WidgetStubCard } from './WidgetStubCard';

export interface PlaceListProps {
  payload: unknown;
  variantId?: string;
}

export function PlaceList({ payload, variantId }: PlaceListProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="place_list" variantId={variantId} payload={payload} />;
}
