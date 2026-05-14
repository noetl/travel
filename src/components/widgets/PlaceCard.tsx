import { Box, Chip, Rating, Stack, Typography } from '@mui/material';
import type { PlaceCardPayload } from '../../contracts/widgets';
import { ActionButton, PhotoStrip, WidgetCard, asPayload, type WidgetComponentProps } from './widgetUtils';

export function PlaceCard({ payload, variantId = 'compact', onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<PlaceCardPayload>(payload);
  const compact = variantId === 'compact';
  const typeLabels = data.types.map((type) => type.replace(/_/g, ' ')).slice(0, compact ? 3 : 6);
  const placeKind = data.types.some((type) => ['airport', 'airport_terminal'].includes(type))
    ? 'airport'
    : data.types.some((type) => ['locality', 'political', 'city'].includes(type))
      ? 'city'
      : 'landmark';
  return (
    <WidgetCard dense={compact} sx={{ width: '100%' }}>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems="stretch">
        <Box
          sx={{
            width: { xs: '100%', sm: compact ? 176 : 240 },
            flexShrink: 0,
            borderRadius: 1.5,
            overflow: 'hidden'
          }}
        >
          <PhotoStrip photos={data.photos} icon="image" />
        </Box>
        <Stack spacing={1} sx={{ minWidth: 0, flex: 1 }}>
          <Stack direction="row" justifyContent="space-between" gap={1} alignItems="flex-start">
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="subtitle1" fontWeight={700} sx={{ overflowWrap: 'anywhere' }}>
                {data.name}
              </Typography>
              <Typography
                variant="body2"
                color="text.secondary"
                sx={{ display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}
              >
                {data.address}
              </Typography>
            </Box>
          </Stack>
          {(data.rating || data.rating_count) ? (
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
              {data.rating ? <Rating value={data.rating} precision={0.1} size="small" readOnly /> : null}
              {data.rating_count ? (
                <Typography variant="caption" color="text.secondary">
                  {data.rating_count.toLocaleString()} reviews
                </Typography>
              ) : null}
            </Stack>
          ) : null}
          <Stack direction="row" gap={0.75} flexWrap="wrap">
            {typeLabels.map((type) => <Chip key={type} label={type} size="small" variant="outlined" />)}
          </Stack>
          {!compact && data.opening_hours ? <Typography variant="body2" color="text.secondary">{data.opening_hours}</Typography> : null}
          {data.ctas?.includes('add_to_itinerary') ? (
            <Stack direction="row" spacing={1} sx={{ pt: 0.5 }}>
              <ActionButton
                label="Add to itinerary"
                actionId={`add_place:${data.place_id}`}
                onWidgetEvent={onWidgetEvent}
                variant="contained"
                value={{ label: data.name, id: data.place_id, kind: placeKind }}
              />
            </Stack>
          ) : null}
        </Stack>
      </Stack>
    </WidgetCard>
  );
}
