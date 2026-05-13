import { WidgetStubCard } from './WidgetStubCard';

export interface PropertyBlockProps {
  payload: unknown;
  variantId?: string;
}

export function PropertyBlock({ payload, variantId }: PropertyBlockProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="property_block" variantId={variantId} payload={payload} />;
}
