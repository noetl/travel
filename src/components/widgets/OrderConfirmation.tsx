import ConfirmationNumberIcon from '@mui/icons-material/ConfirmationNumber';
import { Box, Button, Chip, Divider, Stack, Typography } from '@mui/material';
import type { OrderConfirmationPayload } from '../../contracts/widgets';
import { WidgetCard, asPayload, emitWidgetEvent, money, type WidgetComponentProps } from './widgetUtils';

export function OrderConfirmation({ payload, onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<OrderConfirmationPayload>(payload);
  return (
    <WidgetCard highlighted>
      <Stack spacing={1.5}>
        <Stack direction="row" spacing={1.25} alignItems="center">
          <Box sx={{ width: 44, height: 44, display: 'grid', placeItems: 'center', borderRadius: 2, bgcolor: 'success.main', color: 'white' }}>
            <ConfirmationNumberIcon />
          </Box>
          <Stack>
            <Typography variant="h6">Booking confirmed</Typography>
            <Typography variant="body2" color="text.secondary">Reference {data.booking_reference}</Typography>
          </Stack>
        </Stack>
        <Typography variant="h5" color="primary">{money(data.total_amount, data.total_currency)}</Typography>
        <Stack direction="row" gap={0.75} flexWrap="wrap">
          {data.passengers?.slice(0, 4).map((passenger, index) => <Chip key={index} label={String(passenger.name || passenger.family_name || `Passenger ${index + 1}`)} />)}
        </Stack>
        <Divider />
        <Stack direction="row" spacing={1}>
          {data.ctas?.includes('view_full') ? <Button variant="outlined" onClick={() => emitWidgetEvent(onWidgetEvent, { type: 'widget_cta_click', action_id: `order:${data.order_id}` })}>View full order</Button> : null}
          {data.ctas?.includes('new_search') ? <Button variant="contained" onClick={() => emitWidgetEvent(onWidgetEvent, { type: 'widget_cta_click', action_id: 'new_search' })}>New search</Button> : null}
        </Stack>
      </Stack>
    </WidgetCard>
  );
}
