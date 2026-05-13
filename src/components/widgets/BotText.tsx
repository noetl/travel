import { Box, Stack, Typography } from '@mui/material';
import ReactMarkdown from 'react-markdown';
import type { BotTextPayload } from '../../contracts/widgets';
import { AgentAvatar, WidgetCard, asPayload, compactTime, type WidgetComponentProps } from './widgetUtils';

export function BotText({ payload }: WidgetComponentProps) {
  const data = asPayload<BotTextPayload>(payload);
  return (
    <Stack direction="row" spacing={1.25} alignItems="flex-start" sx={{ maxWidth: 680 }}>
      <AgentAvatar />
      <WidgetCard sx={{ bgcolor: 'background.paper', minWidth: 240 }}>
        <Stack direction="row" justifyContent="space-between" spacing={2}>
          <Typography variant="subtitle2">Muno</Typography>
          {data.timestamp ? <Typography variant="caption" color="text.secondary">{compactTime(data.timestamp)}</Typography> : null}
        </Stack>
        <Box sx={{ mt: 0.75, '& p': { mt: 0, mb: 0.75 }, '& p:last-child': { mb: 0 } }}>
          {data.markdown ? <ReactMarkdown>{data.text}</ReactMarkdown> : <Typography variant="body2">{data.text}</Typography>}
        </Box>
      </WidgetCard>
    </Stack>
  );
}
