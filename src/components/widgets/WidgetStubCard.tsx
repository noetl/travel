import { Card, CardContent, Chip, Stack, Typography } from '@mui/material';
import type { ReactNode } from 'react';

export interface WidgetStubCardProps {
  title: string;
  variantId?: string;
  payload: unknown;
  children?: ReactNode;
}

export function WidgetStubCard({ title, variantId, payload, children }: WidgetStubCardProps) {
  return (
    <Card variant="outlined" sx={{ borderRadius: 2 }}>
      <CardContent>
        <Stack direction="row" gap={1} alignItems="center" sx={{ mb: 1 }}>
          <Typography variant="subtitle2">{title}</Typography>
          {variantId ? <Chip label={variantId} size="small" /> : null}
        </Stack>
        {children}
        <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 12 }}>
          {JSON.stringify(payload, null, 2)}
        </pre>
      </CardContent>
    </Card>
  );
}
