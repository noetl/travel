import { Button, Divider, Stack, Typography } from '@mui/material';
import type { ItinerarySummaryPayload } from '../../contracts/widgets';
import { WidgetCard, asPayload, emitWidgetEvent, money, type WidgetComponentProps } from './widgetUtils';
import { FlightCard } from './FlightCard';
import { HotelCard } from './HotelCard';
import { formatParty } from '../../utils/formatParty';

export function ItinerarySummary({ payload, onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<ItinerarySummaryPayload>(payload);
  return (
    <WidgetCard>
      <Stack spacing={1.75}>
        <Stack direction="row" justifyContent="space-between" spacing={2}>
          <Stack>
            <Typography variant="h6">{data.destination}</Typography>
            <Typography variant="body2" color="text.secondary">{data.dates.from} to {data.dates.to}</Typography>
          </Stack>
          <Typography variant="h6" color="primary">{money(data.total_cost?.amount, data.total_cost?.currency)}</Typography>
        </Stack>
        <Typography variant="body2" color="text.secondary">Party: {formatParty(data.traveller_party)}</Typography>
        {data.picked_flight ? <FlightCard payload={data.picked_flight} variantId="compact" onWidgetEvent={onWidgetEvent} /> : null}
        {data.picked_hotel ? <HotelCard payload={data.picked_hotel} variantId="compact" onWidgetEvent={onWidgetEvent} /> : null}
        {data.notes ? <Typography variant="body2">{data.notes}</Typography> : null}
        <Divider />
        <Stack direction="row" spacing={1}>
          {data.ctas?.includes('confirm') ? <Button variant="contained" onClick={() => emitWidgetEvent(onWidgetEvent, { type: 'widget_cta_click', action_id: 'confirm' })}>Confirm</Button> : null}
          {data.ctas?.includes('edit') ? <Button variant="outlined" onClick={() => emitWidgetEvent(onWidgetEvent, { type: 'widget_cta_click', action_id: 'edit' })}>Edit</Button> : null}
        </Stack>
      </Stack>
    </WidgetCard>
  );
}
