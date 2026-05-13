import { Alert, Snackbar } from '@mui/material';
import type { NotificationPayload } from '../../contracts/widgets';
import { asPayload, type WidgetComponentProps } from './widgetUtils';

export function Notification({ payload }: WidgetComponentProps) {
  const data = asPayload<NotificationPayload>(payload);
  return (
    <Snackbar open anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}>
      <Alert severity={data.kind} variant="filled" sx={{ borderRadius: 2 }}>
        {data.text}
      </Alert>
    </Snackbar>
  );
}
