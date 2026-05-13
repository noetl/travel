import { Button, Stack, TextField, Typography } from '@mui/material';
import { differenceInCalendarDays } from 'date-fns';
import { useMemo, useState } from 'react';
import type { DateRangePickerPayload } from '../../contracts/widgets';
import { WidgetCard, asPayload, emitWidgetEvent, type WidgetComponentProps } from './widgetUtils';

export function DateRangePicker({ payload, onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<DateRangePickerPayload>(payload);
  const [from, setFrom] = useState(data.submitted_value?.from || data.default_from || data.min_date);
  const [to, setTo] = useState(data.submitted_value?.to || data.default_to || data.max_date);
  const nights = useMemo(() => Math.max(1, differenceInCalendarDays(new Date(to), new Date(from))), [from, to]);
  return (
    <WidgetCard>
      <Stack spacing={1.5}>
        <Typography variant="subtitle1">Choose dates</Typography>
        <Stack direction="row" spacing={1.25}>
          <TextField fullWidth label="From" type="date" value={from} inputProps={{ min: data.min_date, max: data.max_date }} onChange={(event) => setFrom(event.target.value)} InputLabelProps={{ shrink: true }} />
          <TextField fullWidth label="To" type="date" value={to} inputProps={{ min: data.min_date, max: data.max_date }} onChange={(event) => setTo(event.target.value)} InputLabelProps={{ shrink: true }} />
        </Stack>
        <Stack direction="row" justifyContent="space-between" alignItems="center">
          <Typography variant="body2" color="text.secondary">{nights} nights</Typography>
          <Button variant="contained" onClick={() => emitWidgetEvent(onWidgetEvent, { type: 'widget_submit', value: { from, to, nights } })}>
            Submit
          </Button>
        </Stack>
      </Stack>
    </WidgetCard>
  );
}
