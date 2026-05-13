import { Grid2 as Grid, Stack, Typography } from '@mui/material';
import type { PlaceListPayload } from '../../contracts/widgets';
import { asPayload, type WidgetComponentProps } from './widgetUtils';
import { PlaceCard } from './PlaceCard';

export function PlaceList({ payload, onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<PlaceListPayload>(payload);
  return (
    <Stack spacing={1.25}>
      <Typography variant="h6">{data.title}</Typography>
      <Grid container spacing={1.5}>
        {data.items.map((item) => (
          <Grid key={item.place_id} size={{ xs: 12, sm: 6, lg: 4 }}>
            <PlaceCard payload={item} variantId="compact" onWidgetEvent={onWidgetEvent} />
          </Grid>
        ))}
      </Grid>
    </Stack>
  );
}
