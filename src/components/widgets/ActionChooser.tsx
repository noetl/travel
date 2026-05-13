import { Box, Button, CardActionArea, Stack, Typography } from '@mui/material';
import type { ActionChooserPayload } from '../../contracts/widgets';
import { EmptyPhoto, WidgetCard, asPayload, emitWidgetEvent, type WidgetComponentProps } from './widgetUtils';

export function ActionChooser({ payload, onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<ActionChooserPayload>(payload);
  return (
    <Stack spacing={1.25}>
      <Typography variant="subtitle1">{data.prompt_text}</Typography>
      <Stack direction="row" gap={1.25} flexWrap="wrap">
        {data.options.map((option) => (
          <Box key={option.action_id} sx={{ width: 190 }}>
            <WidgetCard dense>
              <CardActionArea onClick={() => emitWidgetEvent(onWidgetEvent, { type: 'widget_cta_click', action_id: option.action_id })}>
                {option.illustration_url ? (
                  <Box sx={{ height: 86, backgroundImage: `url(${option.illustration_url})`, backgroundSize: 'cover', backgroundPosition: 'center', borderRadius: 1.5, mb: 1 }} />
                ) : <EmptyPhoto icon="image" />}
                <Stack spacing={1} sx={{ mt: 1 }}>
                  <Typography variant="subtitle2">{option.label}</Typography>
                  <Button size="small" variant="contained">Choose</Button>
                </Stack>
              </CardActionArea>
            </WidgetCard>
          </Box>
        ))}
      </Stack>
    </Stack>
  );
}
