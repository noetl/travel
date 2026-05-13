import { Chip, Grid2 as Grid, Stack, Typography } from '@mui/material';
import type { HotelComparePayload } from '../../contracts/widgets';
import { asPayload, type WidgetComponentProps } from './widgetUtils';
import { HotelCard } from './HotelCard';

export function HotelCompare({ payload, onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<HotelComparePayload>(payload);
  return (
    <Stack spacing={1.5}>
      <Stack direction="row" gap={0.75} alignItems="center" flexWrap="wrap">
        <Typography variant="subtitle1">Compare hotels</Typography>
        {data.comparison_facets.map((facet) => <Chip key={facet} label={facet} size="small" color="primary" variant="outlined" />)}
      </Stack>
      <Grid container spacing={2}>
        {data.items.map((item) => (
          <Grid size={6} key={item.hotel_id}>
            <HotelCard payload={item} variantId="full" onWidgetEvent={onWidgetEvent} />
          </Grid>
        ))}
      </Grid>
    </Stack>
  );
}
