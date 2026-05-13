import { WidgetStubCard } from './WidgetStubCard';

export interface NotificationProps {
  payload: unknown;
  variantId?: string;
}

export function Notification({ payload, variantId }: NotificationProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="notification" variantId={variantId} payload={payload} />;
}
