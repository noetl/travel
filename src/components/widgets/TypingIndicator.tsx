import { Box, Stack, Typography, keyframes } from '@mui/material';
import type { TypingIndicatorPayload } from '../../contracts/widgets';
import { AgentAvatar, asPayload, type WidgetComponentProps } from './widgetUtils';

const pulse = keyframes`
  0%, 80%, 100% { opacity: .35; transform: translateY(0); }
  40% { opacity: 1; transform: translateY(-3px); }
`;

export function TypingIndicator({ payload }: WidgetComponentProps) {
  const data = asPayload<TypingIndicatorPayload>(payload);
  return (
    <Stack direction="row" alignItems="center" spacing={1.25}>
      <AgentAvatar />
      <Stack direction="row" spacing={0.75} alignItems="center" sx={{ px: 1.5, py: 1, borderRadius: 5, bgcolor: 'background.paper' }}>
        {[0, 1, 2].map((index) => (
          <Box key={index} sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: 'primary.main', animation: `${pulse} 1.2s infinite`, animationDelay: `${index * 0.16}s` }} />
        ))}
        <Typography variant="caption" color="text.secondary">{data.agent_name}</Typography>
      </Stack>
    </Stack>
  );
}
