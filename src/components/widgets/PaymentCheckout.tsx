import PaymentIcon from '@mui/icons-material/Payment';
import { Box, Button, Stack, Typography } from '@mui/material';
import type { PaymentCheckoutPayload } from '../../contracts/widgets';
import { WidgetCard, asPayload, emitWidgetEvent, money, type WidgetComponentProps } from './widgetUtils';

// Stripe checkout hand-off (payments_checkout_mode). Nothing has been booked or
// charged. The Muno app (adiona/frontend) opens its Payment Element checkout
// from this envelope; this shell only shows the summary and emits the CTA.
export function PaymentCheckout({ payload, onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<PaymentCheckoutPayload>(payload);
  return (
    <WidgetCard highlighted>
      <Stack spacing={1.5}>
        <Stack direction="row" spacing={1.25} alignItems="center">
          <Box sx={{ width: 44, height: 44, display: 'grid', placeItems: 'center', borderRadius: 2, bgcolor: 'primary.main', color: 'white' }}>
            <PaymentIcon />
          </Box>
          <Stack>
            <Typography variant="h6">{data.kind === 'hotel' ? 'Pay for your hotel' : 'Pay for your flight'}</Typography>
            <Typography variant="body2" color="text.secondary">Nothing is booked or charged until you pay.</Typography>
          </Stack>
        </Stack>
        <Stack spacing={0.25}>
          <Typography variant="subtitle1">{data.title}</Typography>
          {data.subtitle ? <Typography variant="body2" color="text.secondary">{data.subtitle}</Typography> : null}
        </Stack>
        {data.amount ? <Typography variant="h5" color="primary">{money(data.amount, data.currency || '')}</Typography> : null}
        <Button
          variant="contained"
          onClick={() => emitWidgetEvent(onWidgetEvent, { type: 'widget_cta_click', action_id: 'open_checkout' })}
        >
          Continue to payment
        </Button>
      </Stack>
    </WidgetCard>
  );
}
