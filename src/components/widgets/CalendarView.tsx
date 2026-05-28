import EventIcon from '@mui/icons-material/Event';
import EditIcon from '@mui/icons-material/Edit';
import FlightLandIcon from '@mui/icons-material/FlightLand';
import FlightTakeoffIcon from '@mui/icons-material/FlightTakeoff';
import HotelIcon from '@mui/icons-material/Hotel';
import MeetingRoomIcon from '@mui/icons-material/MeetingRoom';
import NotesIcon from '@mui/icons-material/Notes';
import {
  Chip,
  IconButton,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography
} from '@mui/material';
import { format } from 'date-fns';
import { useEffect, useMemo, useState } from 'react';
import { subscribeToCalendarEvents } from '../../api/calendarSubscription';
import type { CalendarViewPayload } from '../../contracts/widgets';
import { WidgetCard, asPayload, emitWidgetEvent, type WidgetComponentProps } from './widgetUtils';

type CalendarEvent = NonNullable<CalendarViewPayload['display_events']>[number];

const EVENT_LABELS: Record<CalendarEvent['type'], string> = {
  flight_depart: 'Flight departs',
  flight_arrive: 'Flight arrives',
  check_in: 'Check-in',
  check_out: 'Check-out',
  activity: 'Activity',
  user_note: 'Note'
};

function eventIcon(type: CalendarEvent['type']) {
  const props = { fontSize: 'small' as const };
  switch (type) {
    case 'flight_depart':
      return <FlightTakeoffIcon {...props} />;
    case 'flight_arrive':
      return <FlightLandIcon {...props} />;
    case 'check_in':
      return <HotelIcon {...props} />;
    case 'check_out':
      return <MeetingRoomIcon {...props} />;
    case 'user_note':
      return <NotesIcon {...props} />;
    default:
      return <EventIcon {...props} />;
  }
}

function toEvent(doc: Record<string, unknown>): CalendarEvent {
  return {
    event_id: String(doc.event_id || doc.id || ''),
    type: (doc.type as CalendarEvent['type']) || 'user_note',
    start_at: String(doc.start_at || ''),
    end_at: (doc.end_at as string | null | undefined) ?? null,
    timezone: String(doc.timezone || 'UTC'),
    title: String(doc.title || 'Calendar event'),
    location: String(doc.location || ''),
    notes: (doc.notes as string | null | undefined) ?? null,
    source_order_id: (doc.source_order_id as string | null | undefined) ?? null,
    source_hotel_id: (doc.source_hotel_id as string | null | undefined) ?? null,
    google_calendar_event_id: (doc.google_calendar_event_id as string | null | undefined) ?? null
  };
}

function eventDate(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return { date: value, time: '' };
  return { date: format(parsed, 'MMM d, yyyy'), time: format(parsed, 'h:mm a') };
}

export function CalendarView({ payload, variantId = 'compact', onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<CalendarViewPayload>(payload);
  const staticEvents = data.display_events?.map((event) => toEvent(event as unknown as Record<string, unknown>));
  const [liveEvents, setLiveEvents] = useState<CalendarEvent[]>([]);
  const events = useMemo(() => staticEvents || liveEvents, [liveEvents, staticEvents]);
  const editable = data.editable && variantId !== 'read_only';

  useEffect(() => {
    if (staticEvents || !data.trip_id) return undefined;
    return subscribeToCalendarEvents(
      data.trip_id,
      data.events_path,
      (items) => setLiveEvents(items.map((item) => toEvent(item)))
    );
  }, [data.trip_id, data.events_path, staticEvents]);

  const emptyText = data.empty_state_text || 'No events yet. Confirm a flight or hotel to populate the schedule.';

  if (!events.length) {
    return (
      <WidgetCard>
        <Stack spacing={1}>
          <Typography variant="subtitle1">Schedule</Typography>
          <Typography variant="body2" color="text.secondary">{emptyText}</Typography>
        </Stack>
      </WidgetCard>
    );
  }

  if (variantId === 'compact') {
    return (
      <WidgetCard>
        <Stack spacing={1}>
          <Typography variant="subtitle1">Schedule</Typography>
          <List dense disablePadding>
            {events.map((event) => {
              const when = eventDate(event.start_at);
              return (
                <ListItem
                  key={event.event_id}
                  disableGutters
                  secondaryAction={editable ? (
                    <IconButton edge="end" aria-label={`edit ${event.title}`} onClick={() => emitWidgetEvent(onWidgetEvent, { type: 'widget_cta_click', action_id: 'edit_event', value: { event_id: event.event_id, action: 'edit_event' } })}>
                      <EditIcon fontSize="small" />
                    </IconButton>
                  ) : null}
                >
                  <ListItemIcon sx={{ minWidth: 36 }}>{eventIcon(event.type)}</ListItemIcon>
                  <ListItemText
                    primary={`${when.date} · ${when.time} · ${event.title}`}
                    secondary={<Stack direction="row" spacing={0.75} alignItems="center"><Chip label={EVENT_LABELS[event.type]} size="small" /><span>{event.location}</span></Stack>}
                  />
                </ListItem>
              );
            })}
          </List>
        </Stack>
      </WidgetCard>
    );
  }

  return (
    <WidgetCard>
      <Stack spacing={1.25}>
        <Stack direction="row" justifyContent="space-between" alignItems="center">
          <Typography variant="subtitle1">Trip calendar</Typography>
          <Chip label={`${events.length} events`} size="small" />
        </Stack>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Date</TableCell>
              <TableCell>Time</TableCell>
              <TableCell>Type</TableCell>
              <TableCell>Title</TableCell>
              <TableCell>Location</TableCell>
              <TableCell>Notes</TableCell>
              {editable ? <TableCell align="right">Actions</TableCell> : null}
            </TableRow>
          </TableHead>
          <TableBody>
            {events.map((event) => {
              const when = eventDate(event.start_at);
              return (
                <TableRow key={event.event_id}>
                  <TableCell>{when.date}</TableCell>
                  <TableCell>{when.time}</TableCell>
                  <TableCell><Stack direction="row" spacing={0.75} alignItems="center">{eventIcon(event.type)}<span>{EVENT_LABELS[event.type]}</span></Stack></TableCell>
                  <TableCell>{event.title}</TableCell>
                  <TableCell>{event.location}</TableCell>
                  <TableCell>{event.notes}</TableCell>
                  {editable ? (
                    <TableCell align="right">
                      <IconButton size="small" aria-label={`edit ${event.title}`} onClick={() => emitWidgetEvent(onWidgetEvent, { type: 'widget_cta_click', action_id: 'edit_event', value: { event_id: event.event_id, action: 'edit_event' } })}>
                        <EditIcon fontSize="small" />
                      </IconButton>
                    </TableCell>
                  ) : null}
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Stack>
    </WidgetCard>
  );
}
