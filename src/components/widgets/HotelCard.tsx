import StarIcon from '@mui/icons-material/Star';
import { Box, Chip, Rating, Stack, Typography } from '@mui/material';
import type { HotelCardPayload } from '../../contracts/widgets';
import { ActionButton, PhotoStrip, WidgetCard, asPayload, money, type WidgetComponentProps } from './widgetUtils';

export function HotelCard({ payload, variantId = 'compact', onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<HotelCardPayload>(payload);
  if (variantId === 'map_marker') {
    return (
      <Chip
        color="primary"
        label={money(data.price_per_night, data.currency)}
        sx={{ fontWeight: 700, boxShadow: 2, borderRadius: 5 }}
      />
    );
  }
  const compact = variantId === 'compact' || variantId === 'in_popover';
  return (
    <WidgetCard highlighted={data.ai_adjustments?.emphasis === 'recommended'} dense={variantId === 'in_popover'}>
      <Stack direction={compact ? 'row' : 'column'} spacing={1.5}>
        <Box sx={{ width: compact ? 140 : '100%', borderRadius: 1.5, overflow: 'hidden', flexShrink: 0 }}>
          <PhotoStrip photos={data.photos} icon="hotel" />
        </Box>
        <Stack spacing={1} sx={{ minWidth: 0, flex: 1 }}>
          <Stack direction="row" justifyContent="space-between" spacing={1}>
            <Typography variant="subtitle1">{data.name}</Typography>
            <Typography variant="subtitle1" color="primary">{money(data.price_per_night, data.currency)}</Typography>
          </Stack>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
            {data.star_rating ? <Rating value={data.star_rating} max={5} size="small" readOnly icon={<StarIcon fontSize="inherit" />} /> : null}
            <Chip label={`${data.score}/10`} size="small" color="success" variant="outlined" />
            {data.rooms_matching ? <Chip label={`Rooms matching: ${data.rooms_matching}`} size="small" /> : null}
          </Stack>
          <Typography variant="body2" color="text.secondary">{data.address || data.distance_from_center || data.location?.city}</Typography>
          {!compact ? (
            <>
              <Stack direction="row" gap={0.75} flexWrap="wrap">
                {data.amenities.slice(0, 8).map((amenity) => <Chip key={amenity} label={amenity} size="small" variant="outlined" />)}
              </Stack>
              {data.score_count ? <Typography variant="body2" color="text.secondary">{data.score_count} traveller reviews</Typography> : null}
            </>
          ) : null}
          {data.ctas?.length ? (
            <Stack direction="row" spacing={1}>
              {data.ctas.includes('watch_in_detail') ? <ActionButton label="Watch In Detail" actionId={`view_hotel:${data.hotel_id}`} onWidgetEvent={onWidgetEvent} /> : null}
              {data.ctas.includes('show_numbers') ? <ActionButton label="Show Numbers" actionId={`pick_hotel:${data.hotel_id}`} onWidgetEvent={onWidgetEvent} variant="contained" /> : null}
            </Stack>
          ) : null}
        </Stack>
      </Stack>
    </WidgetCard>
  );
}
