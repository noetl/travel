import EditIcon from '@mui/icons-material/Edit';
import { IconButton, List, ListItem, ListItemText, Stack, Typography } from '@mui/material';
import type { PropertyBlockPayload } from '../../contracts/widgets';
import { WidgetCard, asPayload, emitWidgetEvent, type WidgetComponentProps } from './widgetUtils';

export function PropertyBlock({ payload, onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<PropertyBlockPayload>(payload);
  return (
    <WidgetCard>
      <Stack spacing={1}>
        <Typography variant="subtitle1">Trip state</Typography>
        <List dense disablePadding>
          {data.slots.map((slot) => (
            <ListItem
              key={slot.label}
              disableGutters
              secondaryAction={slot.edit_action_id ? (
                <IconButton edge="end" aria-label={`edit ${slot.label}`} onClick={() => emitWidgetEvent(onWidgetEvent, { type: 'widget_cta_click', action_id: slot.edit_action_id })}>
                  <EditIcon fontSize="small" />
                </IconButton>
              ) : null}
            >
              <ListItemText primary={slot.label} secondary={slot.missing ? 'Missing' : String(slot.value ?? '-')} />
            </ListItem>
          ))}
        </List>
      </Stack>
    </WidgetCard>
  );
}
