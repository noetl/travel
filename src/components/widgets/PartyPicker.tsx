import { Button, MenuItem, Select, Stack, Typography } from '@mui/material';
import { useState } from 'react';
import type { PartyPickerPayload } from '../../contracts/widgets';
import { StepperButton, WidgetCard, asPayload, emitWidgetEvent, type WidgetComponentProps } from './widgetUtils';

export function PartyPicker({ payload, onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<PartyPickerPayload>(payload);
  const [rooms, setRooms] = useState(data.submitted_value?.rooms || 1);
  const [adults, setAdults] = useState(data.submitted_value?.adults || 2);
  const [children, setChildren] = useState(data.submitted_value?.children || []);
  const setChildCount = (count: number) => {
    setChildren((current) => Array.from({ length: count }, (_, index) => current[index] || { age: 8 }));
  };
  const row = (label: string, value: number, set: (value: number) => void, max: number, min = 0) => (
    <Stack direction="row" alignItems="center" justifyContent="space-between">
      <Typography>{label}</Typography>
      <Stack direction="row" alignItems="center" spacing={1}>
        <StepperButton direction="down" onClick={() => set(Math.max(min, value - 1))} />
        <Typography fontWeight={700} sx={{ width: 24, textAlign: 'center' }}>{value}</Typography>
        <StepperButton direction="up" onClick={() => set(Math.min(max, value + 1))} />
      </Stack>
    </Stack>
  );
  return (
    <WidgetCard>
      <Stack spacing={1.5}>
        <Typography variant="subtitle1">Travellers</Typography>
        {row('Rooms', rooms, setRooms, data.rooms_max, 1)}
        {row('Adults', adults, setAdults, data.adults_max, 1)}
        {row('Children', children.length, setChildCount, data.children_max, 0)}
        {data.allow_child_ages && children.map((child, index) => (
          <Stack key={index} direction="row" alignItems="center" justifyContent="space-between">
            <Typography variant="body2">Child {index + 1} age</Typography>
            <Select
              size="small"
              value={child.age}
              onChange={(event) => setChildren((current) => current.map((item, i) => i === index ? { age: Number(event.target.value) } : item))}
            >
              {Array.from({ length: 18 }, (_, age) => <MenuItem key={age} value={age}>{age === 0 ? '< 1 year' : `${age} year`}</MenuItem>)}
            </Select>
          </Stack>
        ))}
        <Button variant="contained" onClick={() => emitWidgetEvent(onWidgetEvent, { type: 'widget_submit', value: { rooms, adults, children } })}>
          Submit
        </Button>
      </Stack>
    </WidgetCard>
  );
}
