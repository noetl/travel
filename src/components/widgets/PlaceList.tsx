import { Grid2 as Grid, Stack, Typography } from '@mui/material';
import type { PlaceListPayload } from '../../contracts/widgets';
import { asPayload, type WidgetComponentProps } from './widgetUtils';
import { PlaceCard } from './PlaceCard';

export function PlaceList({ payload, onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<PlaceListPayload>(payload);
  const singleItem = data.items.length === 1;
  return (
    <Stack spacing={1.25} sx={{ width: '100%', maxWidth: 920 }}>
      <Typography variant="h6">{data.title}</Typography>
      <Grid container spacing={1.5}>
        {data.items.map((item) => (
          <Grid key={item.place_id} size={{ xs: 12, md: singleItem ? 12 : 6 }}>
            <PlaceCard payload={item} variantId={singleItem ? 'default' : 'compact'} onWidgetEvent={onWidgetEvent} />
          </Grid>
        ))}
      </Grid>
    </Stack>
  );
}
