import { WidgetStubCard } from './WidgetStubCard';

export interface OrderConfirmationProps {
  payload: unknown;
  variantId?: string;
}

export function OrderConfirmation({ payload, variantId }: OrderConfirmationProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="order_confirmation" variantId={variantId} payload={payload} />;
}
