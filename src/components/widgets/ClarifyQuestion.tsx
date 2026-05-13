import { WidgetStubCard } from './WidgetStubCard';

export interface ClarifyQuestionProps {
  payload: unknown;
  variantId?: string;
}

export function ClarifyQuestion({ payload, variantId }: ClarifyQuestionProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="clarify_question" variantId={variantId} payload={payload} />;
}
