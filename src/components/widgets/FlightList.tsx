import { Chip, Stack, Typography } from '@mui/material';
import type { FlightListPayload } from '../../contracts/widgets';
import { asPayload, type WidgetComponentProps } from './widgetUtils';
import { FlightCard } from './FlightCard';

export function FlightList({ payload, onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<FlightListPayload>(payload);
  return (
    <Stack spacing={1.25}>
      <Stack direction="row" alignItems="center" justifyContent="space-between">
        <Typography variant="h6">{data.title}</Typography>
        <Chip label={`${data.total_count} offers · ${data.currency}`} size="small" />
      </Stack>
      {data.items.map((item) => (
        <FlightCard key={item.offer_id} payload={{ ...item, ai_adjustments: item.offer_id === data.emphasis_offer_id ? { emphasis: 'cheapest' } : item.ai_adjustments }} variantId="compact" onWidgetEvent={onWidgetEvent} />
      ))}
    </Stack>
  );
}
