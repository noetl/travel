import LocalActivityIcon from '@mui/icons-material/LocalActivity';
import { Box, Chip, Stack, Typography } from '@mui/material';
import type { ActivityListPayload } from '../../contracts/widgets';
import { ActionButton, WidgetCard, asPayload, money, type WidgetComponentProps } from './widgetUtils';

export function ActivityList({ payload, onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<ActivityListPayload>(payload);
  return (
    <Stack spacing={1.25}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={1}>
        <Typography variant="h6">{data.title}</Typography>
        <Chip label={`${data.total_count} activities`} size="small" />
      </Stack>
      {data.filter_summary ? <Typography variant="body2" color="text.secondary">{data.filter_summary}</Typography> : null}
      {data.items.map((item) => (
        <WidgetCard key={item.activity_code} dense>
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
              <LocalActivityIcon fontSize="small" />
            </Box>
            <Stack spacing={0.75} sx={{ minWidth: 0, flex: 1 }}>
              <Stack direction="row" justifyContent="space-between" spacing={1}>
                <Typography variant="subtitle1" sx={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {item.name}
                </Typography>
                <Typography variant="subtitle1" color="primary" sx={{ flexShrink: 0 }}>
                  {money(item.amount_from, item.currency)}
                </Typography>
              </Stack>
              <Stack direction="row" gap={0.75} flexWrap="wrap">
                {item.type ? <Chip label={item.type} size="small" variant="outlined" /> : null}
                {item.country ? <Chip label={item.country} size="small" variant="outlined" /> : null}
                {item.modalities_count ? <Chip label={`${item.modalities_count} options`} size="small" /> : null}
              </Stack>
              {item.description ? <Typography variant="body2" color="text.secondary">{item.description}</Typography> : null}
              {item.modalities?.length ? (
                <Typography variant="caption" color="text.secondary">
                  {item.modalities.map((modality) => modality.name || modality.code).filter(Boolean).join(' · ')}
                </Typography>
              ) : null}
              {item.ctas?.length ? (
                <Stack direction="row" spacing={1}>
                  {item.ctas.includes('add_to_itinerary') ? (
                    <ActionButton
                      label="Add"
                      actionId={`pick_activity:${item.activity_code}`}
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
      ))}
    </Stack>
  );
}
