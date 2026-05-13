import { WidgetStubCard } from './WidgetStubCard';

export interface FilterPanelProps {
  payload: unknown;
  variantId?: string;
}

export function FilterPanel({ payload, variantId }: FilterPanelProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="filter_panel" variantId={variantId} payload={payload} />;
}
