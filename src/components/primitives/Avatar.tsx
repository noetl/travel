import { Avatar as MuiAvatar } from '@mui/material';

export function Avatar({ label }: { label: string }) {
  return <MuiAvatar>{label.slice(0, 1).toUpperCase()}</MuiAvatar>;
}
