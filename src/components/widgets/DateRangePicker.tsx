import { WidgetStubCard } from './WidgetStubCard';

export interface DateRangePickerProps {
  payload: unknown;
  variantId?: string;
}

export function DateRangePicker({ payload, variantId }: DateRangePickerProps) {
  // TODO Round 6b: replace this JSON stub with the real Material rendering.
  return <WidgetStubCard title="date_range_picker" variantId={variantId} payload={payload} />;
}
