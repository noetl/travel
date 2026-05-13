import { Skeleton, Stack, Typography } from '@mui/material';
import type { LoadingCardPayload } from '../../contracts/widgets';
import { WidgetCard, asPayload, type WidgetComponentProps } from './widgetUtils';

export function LoadingCard({ payload }: WidgetComponentProps) {
  const data = asPayload<LoadingCardPayload>(payload);
  return (
    <WidgetCard>
      <Stack spacing={1.25}>
        <Typography variant="subtitle2">{data.tool_name}</Typography>
        <Skeleton variant="rounded" height={24} />
        <Skeleton variant="rounded" height={72} />
        <Skeleton variant="rounded" height={24} width="70%" />
        <Typography variant="caption" color="text.secondary">
          Started {data.started_at}
          {data.expected_duration_seconds ? `, usually ${data.expected_duration_seconds}s` : ''}
        </Typography>
      </Stack>
    </WidgetCard>
  );
}
