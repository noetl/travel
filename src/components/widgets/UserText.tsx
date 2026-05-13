import { WidgetStubCard } from './WidgetStubCard';

export interface UserTextProps {
  payload: unknown;
  variantId?: string;
}

export function UserText({ payload, variantId }: UserTextProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="user_text" variantId={variantId} payload={payload} />;
}
