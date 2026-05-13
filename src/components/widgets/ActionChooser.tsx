import { WidgetStubCard } from './WidgetStubCard';

export interface ActionChooserProps {
  payload: unknown;
  variantId?: string;
}

export function ActionChooser({ payload, variantId }: ActionChooserProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="action_chooser" variantId={variantId} payload={payload} />;
}
