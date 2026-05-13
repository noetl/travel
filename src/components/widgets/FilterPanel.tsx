import { Button, Checkbox, FormControlLabel, FormGroup, Slider, Stack, Typography } from '@mui/material';
import { useState } from 'react';
import type { FilterPanelPayload } from '../../contracts/widgets';
import { WidgetCard, asPayload, emitWidgetEvent, type WidgetComponentProps } from './widgetUtils';

export function FilterPanel({ payload, onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<FilterPanelPayload>(payload);
  const [budget, setBudget] = useState<[number, number]>([data.applied.budget_min || data.budget_range.min, data.applied.budget_max || data.budget_range.max]);
  const [categories, setCategories] = useState<string[]>(data.applied.hotel_category || []);
  const [rating, setRating] = useState(data.applied.guest_rating_min || 0);
  const emit = (action_id = 'filters:apply') => emitWidgetEvent(onWidgetEvent, { type: 'widget_cta_click', action_id, value: { hotel_category: categories, budget_min: budget[0], budget_max: budget[1], guest_rating_min: rating } });
  return (
    <WidgetCard>
      <Stack spacing={2}>
        <Stack direction="row" justifyContent="space-between" alignItems="center">
          <Typography variant="subtitle1">Filters</Typography>
          {data.ctas?.includes('clear_all') ? <Button size="small" onClick={() => { setCategories([]); setRating(0); setBudget([data.budget_range.min, data.budget_range.max]); emit('filters:clear_all'); }}>Clear All</Button> : null}
        </Stack>
        <FormGroup>
          {data.hotel_category_options.map((option) => (
            <FormControlLabel key={option} control={<Checkbox checked={categories.includes(option)} onChange={(_, checked) => setCategories((current) => checked ? [...current, option] : current.filter((item) => item !== option))} />} label={option} />
          ))}
        </FormGroup>
        <Stack spacing={1}>
          <Typography variant="body2">Budget ({data.budget_range.currency})</Typography>
          <Slider value={budget} min={data.budget_range.min} max={data.budget_range.max} onChange={(_, next) => setBudget(next as [number, number])} valueLabelDisplay="auto" />
        </Stack>
        <FormGroup>
          {data.guest_rating_options.map((option) => (
            <FormControlLabel key={option} control={<Checkbox checked={rating === option} onChange={(_, checked) => setRating(checked ? option : 0)} />} label={`${option}+ guest rating`} />
          ))}
        </FormGroup>
        {data.ctas?.includes('apply') ? <Button variant="contained" onClick={() => emit()}>Apply</Button> : null}
      </Stack>
    </WidgetCard>
  );
}
