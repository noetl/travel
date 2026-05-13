import { Typography } from '@mui/material';

export function TypingIndicator({ agentName = 'Muno' }: { agentName?: string }) {
  return <Typography variant="body2" color="text.secondary">{agentName} is typing...</Typography>;
}
