import AirportShuttleIcon from '@mui/icons-material/AirportShuttle';
import { Box, Chip, Stack, Typography } from '@mui/material';
import type { TransferListPayload } from '../../contracts/widgets';
import { ActionButton, WidgetCard, asPayload, money, type WidgetComponentProps } from './widgetUtils';

export function TransferList({ payload, onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<TransferListPayload>(payload);
  return (
    <Stack spacing={1.25}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={1}>
        <Typography variant="h6">{data.title}</Typography>
        <Chip label={`${data.total_count} transfers`} size="small" />
      </Stack>
      {data.route_summary ? <Typography variant="body2" color="text.secondary">{data.route_summary}</Typography> : null}
      {data.items.map((item) => {
        const title = item.vehicle_name || item.category_name || item.transfer_type || 'Transfer';
        return (
          <WidgetCard key={item.transfer_id} dense>
            <Stack direction="row" spacing={1.5} alignItems="flex-start">
              <Box
                sx={{
                  width: 44,
                  height: 44,
                  borderRadius: 1.5,
                  bgcolor: 'action.hover',
                  color: 'primary.main',
                  display: 'grid',
                  placeItems: 'center',
                  flexShrink: 0
                }}
              >
                <AirportShuttleIcon fontSize="small" />
              </Box>
              <Stack spacing={0.75} sx={{ minWidth: 0, flex: 1 }}>
                <Stack direction="row" justifyContent="space-between" spacing={1}>
                  <Typography variant="subtitle1" sx={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {title}
                  </Typography>
                  <Typography variant="subtitle1" color="primary" sx={{ flexShrink: 0 }}>
                    {money(item.total_amount, item.currency)}
                  </Typography>
                </Stack>
                <Stack direction="row" gap={0.75} flexWrap="wrap">
                  {item.category_name ? <Chip label={item.category_name} size="small" variant="outlined" /> : null}
                  {item.transfer_type ? <Chip label={item.transfer_type} size="small" variant="outlined" /> : null}
                  {item.direction ? <Chip label={item.direction} size="small" /> : null}
                </Stack>
                {item.detail ? <Typography variant="body2" color="text.secondary">{item.detail}</Typography> : null}
                {item.ctas?.length ? (
                  <Stack direction="row" spacing={1}>
                    {item.ctas.includes('add_to_itinerary') ? (
                      <ActionButton
                        label="Add"
                        actionId={`pick_transfer:${item.transfer_id}`}
                        value={item}
                        onWidgetEvent={onWidgetEvent}
                        variant="contained"
                      />
                    ) : null}
                  </Stack>
                ) : null}
              </Stack>
            </Stack>
          </WidgetCard>
        );
      })}
    </Stack>
  );
}
