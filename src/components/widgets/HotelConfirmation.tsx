import HotelIcon from '@mui/icons-material/Hotel';
import { Box, Button, Chip, Divider, Stack, Typography } from '@mui/material';
import type { HotelConfirmationPayload } from '../../contracts/widgets';
import { WidgetCard, asPayload, emitWidgetEvent, money, type WidgetComponentProps } from './widgetUtils';

function formatDate(value?: string): string {
  if (!value) return '';
  return value.includes('T') ? value.slice(0, 10) : value;
}

export function HotelConfirmation({ payload, onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<HotelConfirmationPayload>(payload);
  const checkIn = formatDate(data.check_in);
  const checkOut = formatDate(data.check_out);
  const stay = checkIn && checkOut ? `${checkIn} → ${checkOut}` : checkIn || checkOut;

  return (
    <WidgetCard highlighted>
      <Stack spacing={1.5}>
        <Stack direction="row" spacing={1.25} alignItems="center">
          <Box sx={{ width: 44, height: 44, display: 'grid', placeItems: 'center', borderRadius: 2, bgcolor: 'success.main', color: 'white' }}>
            <HotelIcon />
          </Box>
          <Stack>
            <Typography variant="h6">Hotel booked</Typography>
            <Typography variant="body2" color="text.secondary">Reference {data.booking_reference}</Typography>
          </Stack>
          {data.status ? <Chip size="small" color="success" label={data.status} sx={{ ml: 'auto' }} /> : null}
        </Stack>
        <Stack spacing={0.25}>
          <Typography variant="subtitle1">{data.hotel_name}</Typography>
          {data.destination ? <Typography variant="body2" color="text.secondary">{data.destination}</Typography> : null}
          {stay ? <Typography variant="body2" color="text.secondary">{stay}</Typography> : null}
        </Stack>
        <Typography variant="h5" color="primary">{money(data.total_amount, data.total_currency)}</Typography>
        <Divider />
        <Stack direction="row" spacing={1} flexWrap="wrap">
          {data.ctas?.includes('new_search') ? (
            <Button
              variant="contained"
              onClick={() => emitWidgetEvent(onWidgetEvent, { type: 'widget_cta_click', action_id: 'new_search' })}
            >
              New search
            </Button>
          ) : null}
        </Stack>
      </Stack>
    </WidgetCard>
  );
}
