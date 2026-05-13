import { WidgetStubCard } from './WidgetStubCard';

export interface LoadingCardProps {
  payload: unknown;
  variantId?: string;
}

export function LoadingCard({ payload, variantId }: LoadingCardProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="loading_card" variantId={variantId} payload={payload} />;
}
