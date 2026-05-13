import { WidgetStubCard } from './WidgetStubCard';

export interface BotTextProps {
  payload: unknown;
  variantId?: string;
}

export function BotText({ payload, variantId }: BotTextProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="bot_text" variantId={variantId} payload={payload} />;
}
