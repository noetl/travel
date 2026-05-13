import { Chip, Stack, Typography } from '@mui/material';
import type { ClarifyQuestionPayload } from '../../contracts/widgets';
import { WidgetCard, asPayload, emitWidgetEvent, type WidgetComponentProps } from './widgetUtils';

export function ClarifyQuestion({ payload, onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<ClarifyQuestionPayload>(payload);
  return (
    <WidgetCard>
      <Typography variant="subtitle1">{data.question_text}</Typography>
      <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mt: 1.5 }}>
        {data.options.map((option) => (
          <Chip
            key={option.action_id}
            label={option.label}
            clickable
            color="primary"
            variant="outlined"
            onClick={() => emitWidgetEvent(onWidgetEvent, { type: 'widget_cta_click', action_id: option.action_id })}
          />
        ))}
      </Stack>
    </WidgetCard>
  );
}
