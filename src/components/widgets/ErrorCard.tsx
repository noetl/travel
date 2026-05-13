import { WidgetStubCard } from './WidgetStubCard';

export interface ErrorCardProps {
  payload: unknown;
  variantId?: string;
}

export function ErrorCard({ payload, variantId }: ErrorCardProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="error_card" variantId={variantId} payload={payload} />;
}
