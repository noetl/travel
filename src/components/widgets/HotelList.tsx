import { Alert, Button, Chip, Stack, Typography } from '@mui/material';
import type { HotelListPayload } from '../../contracts/widgets';
import { asPayload, emitWidgetEvent, type WidgetComponentProps } from './widgetUtils';
import { HotelCard } from './HotelCard';

export function HotelList({ payload, onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<HotelListPayload>(payload);
  return (
    <Stack spacing={1.25}>
      <Stack direction="row" alignItems="center" justifyContent="space-between">
        <Typography variant="h6">{data.title}</Typography>
        <Chip label={`${data.total_count} stays`} size="small" />
      </Stack>
      {data.upsell_banner ? (
        <Alert severity="info" action={<Button size="small" onClick={() => emitWidgetEvent(onWidgetEvent, { type: 'widget_cta_click', action_id: data.upsell_banner?.action_id })}>{data.upsell_banner.action_label}</Button>}>
          {data.upsell_banner.text}
        </Alert>
      ) : null}
      {data.filter_summary ? <Typography variant="body2" color="text.secondary">{data.filter_summary}</Typography> : null}
      {data.items.map((item) => <HotelCard key={item.hotel_id} payload={item} variantId="compact" onWidgetEvent={onWidgetEvent} />)}
    </Stack>
  );
}
