import FlightIcon from '@mui/icons-material/Flight';
import { Box, Chip, Divider, Stack, Typography } from '@mui/material';
import type { FlightCardPayload } from '../../contracts/widgets';
import { ActionButton, LabelValue, WidgetCard, asPayload, compactTime, money, type WidgetComponentProps } from './widgetUtils';

export function FlightCard({ payload, variantId = 'compact', onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<FlightCardPayload>(payload);
  const first = data.itineraries[0]?.segments[0];
  const lastSegments = data.itineraries[0]?.segments || [];
  const last = lastSegments[lastSegments.length - 1] || first;
  const isCompact = variantId === 'compact' || variantId === 'in_popover';
  return (
    <WidgetCard highlighted={data.ai_adjustments?.emphasis === 'cheapest'}>
      <Stack spacing={1.25}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={2}>
          <Stack direction="row" spacing={1} alignItems="center">
            <Box sx={{ width: 36, height: 36, borderRadius: 2, bgcolor: 'primary.main', color: 'white', display: 'grid', placeItems: 'center' }}>
              <FlightIcon fontSize="small" />
            </Box>
            <Stack>
              <Typography variant="subtitle1">{data.carriers.join(', ') || data.validating_airline || 'Flight'}</Typography>
              <Typography variant="caption" color="text.secondary">{data.duration} · {data.stops === 0 ? 'Nonstop' : `${data.stops} stop${data.stops > 1 ? 's' : ''}`}</Typography>
            </Stack>
          </Stack>
          <Typography variant="h6">{money(data.price.total, data.price.currency)}</Typography>
        </Stack>
        <Stack direction="row" alignItems="center" spacing={1.5}>
          <LabelValue label="Depart" value={`${first?.departure.iata || '?'} ${compactTime(first?.departure.at)}`} />
          <Divider flexItem orientation="vertical" />
          <LabelValue label="Arrive" value={`${last?.arrival.iata || '?'} ${compactTime(last?.arrival.at)}`} />
          <Divider flexItem orientation="vertical" />
          <LabelValue label="Carrier" value={first?.carrier || data.validating_airline} />
        </Stack>
        {!isCompact ? (
          <Stack spacing={0.75}>
            {data.itineraries.flatMap((itinerary) => itinerary.segments).map((segment, index) => (
              <Chip key={`${segment.carrier}-${segment.flight_number}-${index}`} label={`${segment.departure.iata} → ${segment.arrival.iata} · ${segment.duration}`} variant="outlined" />
            ))}
          </Stack>
        ) : null}
        {data.ctas?.length ? (
          <Stack direction="row" spacing={1}>
            {data.ctas.includes('view_details') ? <ActionButton label="Watch In Detail" actionId={`view_offer:${data.offer_id}`} onWidgetEvent={onWidgetEvent} /> : null}
            {data.ctas.includes('book_this') ? <ActionButton label="Book This" actionId={`pick_offer:${data.offer_id}`} onWidgetEvent={onWidgetEvent} variant="contained" /> : null}
          </Stack>
        ) : null}
      </Stack>
    </WidgetCard>
  );
}
