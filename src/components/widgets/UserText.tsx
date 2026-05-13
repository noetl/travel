import { Avatar, Stack, Typography } from '@mui/material';
import type { UserTextPayload } from '../../contracts/widgets';
import { WidgetCard, asPayload, compactTime, type WidgetComponentProps } from './widgetUtils';

export function UserText({ payload }: WidgetComponentProps) {
  const data = asPayload<UserTextPayload>(payload);
  return (
    <Stack direction="row" spacing={1.25} justifyContent="flex-end" alignItems="flex-start" sx={{ maxWidth: 680, ml: 'auto' }}>
      <WidgetCard sx={{ bgcolor: '#FFFFFF', minWidth: 220 }}>
        <Stack direction="row" justifyContent="space-between" spacing={2}>
          <Typography variant="subtitle2">You</Typography>
          {data.timestamp ? <Typography variant="caption" color="text.secondary">{compactTime(data.timestamp)}</Typography> : null}
        </Stack>
        <Typography sx={{ mt: 0.75 }} variant="body2">{data.text}</Typography>
      </WidgetCard>
      <Avatar src={data.user_avatar_url} sx={{ width: 34, height: 34, bgcolor: 'secondary.main' }}>U</Avatar>
    </Stack>
  );
}
