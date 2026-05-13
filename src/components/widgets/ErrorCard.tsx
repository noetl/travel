import { Alert, Button, Stack } from '@mui/material';
import type { ErrorCardPayload } from '../../contracts/widgets';
import { asPayload, emitWidgetEvent, type WidgetComponentProps } from './widgetUtils';

export function ErrorCard({ payload, onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<ErrorCardPayload>(payload);
  return (
    <Alert
      severity="error"
      sx={{ borderRadius: 2 }}
      action={
        <Stack direction="row" spacing={1}>
          {data.retry_action_id ? (
            <Button color="inherit" size="small" onClick={() => emitWidgetEvent(onWidgetEvent, { type: 'widget_cta_click', action_id: data.retry_action_id })}>
              Retry
            </Button>
          ) : null}
          {data.contact_support ? <Button color="inherit" size="small">Support</Button> : null}
        </Stack>
      }
    >
      <strong>{data.title}</strong>
      <br />
      {data.description}
    </Alert>
  );
}
