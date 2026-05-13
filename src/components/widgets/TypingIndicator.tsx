import { WidgetStubCard } from './WidgetStubCard';

export interface TypingIndicatorProps {
  payload: unknown;
  variantId?: string;
}

export function TypingIndicator({ payload, variantId }: TypingIndicatorProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="typing_indicator" variantId={variantId} payload={payload} />;
}
