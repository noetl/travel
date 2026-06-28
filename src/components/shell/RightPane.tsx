import { Box, Typography } from '@mui/material';
import { useTranslation } from 'react-i18next';
import type { WidgetEnvelope } from '../../contracts/widgets';
import { WidgetRenderer } from '../WidgetRenderer';
import { formatParty } from '../../utils/formatParty';

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function moneyLabel(value: unknown): string {
  const item = asRecord(value);
  const amount = item.amount;
  const currency = String(item.currency || 'USD');
  return amount === null || amount === undefined || amount === '' ? '' : `${currency} ${amount}`;
}

function regionLabel(slotState: Record<string, unknown>): string {
  const region = asRecord(slotState.region);
  // Playbook stores both a nested region object and flat region_label / region_city_code
  // scalars at the top level of final_slot_state.  Read whichever is non-empty.
  return (
    String(region.label || region.city || region.city_code || '') ||
    String(slotState.region_label || '')
  );
}

function datesLabel(slotState: Record<string, unknown>): string {
  const start = String(slotState.check_in_date || '');
  const end = String(slotState.check_out_date || '');
  if (start && end) return `${start} -> ${end}`;
  return start || end;
}

function budgetLabel(slotState: Record<string, unknown>): string {
  const min = moneyLabel(slotState.budget_min);
  const max = moneyLabel(slotState.budget_max);
  if (min && max) return `${min} - ${max}`;
  return min || max;
}

function amenitiesLabel(slotState: Record<string, unknown>): string {
  const amenities = slotState.amenities_required;
  return Array.isArray(amenities) ? amenities.map(String).filter(Boolean).join(', ') : '';
}

function propertyBlockEnvelope(slotState: Record<string, unknown>): WidgetEnvelope {
  const party = asRecord(slotState.party);
  const slots = [
    { label: 'Region', value: regionLabel(slotState), edit_action_id: 'edit_region' },
    { label: 'Dates', value: datesLabel(slotState), edit_action_id: 'edit_dates' },
    {
      label: 'Party',
      value: Object.keys(party).length > 0 ? formatParty(party) || JSON.stringify(party) : '',
      edit_action_id: 'edit_party'
    },
    {
      label: 'Star rating',
      value: slotState.star_rating_min === null || slotState.star_rating_min === undefined ? '' : `${slotState.star_rating_min}+`,
      edit_action_id: 'edit_star_rating'
    },
    { label: 'Budget', value: budgetLabel(slotState), edit_action_id: 'edit_budget' },
    { label: 'Bed type', value: String(slotState.bed_type || ''), edit_action_id: 'edit_bed_type' },
    { label: 'Amenities', value: amenitiesLabel(slotState), edit_action_id: 'edit_amenities' }
  ].map((slot) => ({
    label: slot.label,
    value: slot.value || null,
    edit_action_id: slot.edit_action_id,
    missing: !slot.value
  }));

  return {
    widget_type: 'property_block',
    variant: 'default',
    payload: { slots },
    schema_version: 1
  };
}

export function RightPane({ slotState }: { slotState: Record<string, unknown> }) {
  const { t } = useTranslation();
  return (
    <Box sx={{ height: '100%', borderLeft: '1px solid', borderColor: 'divider', bgcolor: 'background.paper', p: 2, overflow: 'auto' }}>
      <Typography variant="h6" sx={{ mb: 2 }}>{t('right_pane.title')}</Typography>
      <WidgetRenderer envelope={propertyBlockEnvelope(slotState)} />
    </Box>
  );
}
