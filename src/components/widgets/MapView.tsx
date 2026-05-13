import { WidgetStubCard } from './WidgetStubCard';

export interface MapViewProps {
  payload: unknown;
  variantId?: string;
}

export function MapView({ payload, variantId }: MapViewProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="map_view" variantId={variantId} payload={payload} />;
}
