import { Chip, Rating, Stack, Typography } from '@mui/material';
import type { PlaceCardPayload } from '../../contracts/widgets';
import { ActionButton, PhotoStrip, WidgetCard, asPayload, type WidgetComponentProps } from './widgetUtils';

export function PlaceCard({ payload, variantId = 'compact', onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<PlaceCardPayload>(payload);
  const compact = variantId === 'compact';
  return (
    <WidgetCard dense={compact}>
      <Stack spacing={1}>
        <PhotoStrip photos={data.photos} icon="image" />
        <Typography variant="subtitle1">{data.name}</Typography>
        <Stack direction="row" spacing={1} alignItems="center">
          {data.rating ? <Rating value={data.rating} precision={0.1} size="small" readOnly /> : null}
          {data.rating_count ? <Typography variant="caption" color="text.secondary">{data.rating_count} reviews</Typography> : null}
        </Stack>
        <Stack direction="row" gap={0.5} flexWrap="wrap">
          {data.types.slice(0, compact ? 3 : 6).map((type) => <Chip key={type} label={type} size="small" variant="outlined" />)}
        </Stack>
        {!compact && data.opening_hours ? <Typography variant="body2" color="text.secondary">{data.opening_hours}</Typography> : null}
        <Typography variant="body2" color="text.secondary">{data.address}</Typography>
        {data.ctas?.includes('add_to_itinerary') ? <ActionButton label="Add to itinerary" actionId={`add_place:${data.place_id}`} onWidgetEvent={onWidgetEvent} variant="contained" /> : null}
      </Stack>
    </WidgetCard>
  );
}
