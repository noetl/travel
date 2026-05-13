import { Autocomplete, Button, Stack, TextField } from '@mui/material';
import { useState } from 'react';
import type { PlaceAutocompleteInputPayload } from '../../contracts/widgets';
import { WidgetCard, asPayload, emitWidgetEvent, type WidgetComponentProps } from './widgetUtils';

export function PlaceAutocompleteInput({ payload, onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<PlaceAutocompleteInputPayload>(payload);
  const [value, setValue] = useState<PlaceAutocompleteInputPayload['suggestions'][number] | string | null>(data.submitted_value || null);
  const submit = () => {
    const submitted = typeof value === 'string' ? { label: value, id: value, kind: 'city' as const } : value;
    if (submitted) emitWidgetEvent(onWidgetEvent, { type: 'widget_submit', value: submitted });
  };
  return (
    <WidgetCard>
      <Stack direction="row" spacing={1.25} alignItems="center">
        <Autocomplete
          fullWidth
          freeSolo
          options={data.suggestions}
          value={value}
          getOptionLabel={(option) => typeof option === 'string' ? option : option.label}
          onChange={(_, next) => {
            setValue(next);
            if (data.submit_on_select && next) {
              const submitted = typeof next === 'string' ? { label: next, id: next, kind: 'city' as const } : next;
              emitWidgetEvent(onWidgetEvent, { type: 'widget_submit', value: submitted });
            }
          }}
          onInputChange={(_, input) => setValue(input)}
          renderInput={(params) => <TextField {...params} label={data.placeholder} />}
        />
        <Button variant="contained" onClick={submit}>Submit</Button>
      </Stack>
    </WidgetCard>
  );
}
