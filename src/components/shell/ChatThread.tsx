import AddCommentIcon from '@mui/icons-material/AddComment';
import MenuIcon from '@mui/icons-material/Menu';
import LuggageIcon from '@mui/icons-material/Luggage';
import { Alert, Box, Button, CircularProgress, IconButton, Paper, Stack, TextField, Tooltip, Typography } from '@mui/material';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { WidgetEnvelope } from '../../contracts/widgets';
import { cancelExecution, executePlaybook, getExecution, waitForExecutionCompletion } from '../../api/noetlClient';
import { useMunoAuth } from '../../auth/MunoAuthProvider';
import { WidgetRenderer } from '../WidgetRenderer';
import type { ChatHistorySummary, SidebarView } from './Sidebar';
import type { WidgetEvent } from '../widgets/widgetUtils';

const ITINERARY_PLAYBOOK = 'muno/playbooks/itinerary-planner';
const THREAD_STORAGE_KEY = 'travel:current_thread_id';

function mintThreadId(): string {
  return `travel-ui-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function loadStoredThreadId(): string {
  try {
    const stored = window.localStorage.getItem(THREAD_STORAGE_KEY);
    if (stored && stored.trim()) return stored;
  } catch {
    // localStorage unavailable (private mode, etc.) — fall through to a fresh id
  }
  const fresh = mintThreadId();
  try {
    window.localStorage.setItem(THREAD_STORAGE_KEY, fresh);
  } catch {
    /* ignore */
  }
  return fresh;
}

function clearStoredThreadId() {
  try {
    window.localStorage.removeItem(THREAD_STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

type ChatMessage =
  | { id: string; role: 'user'; text: string; view: SidebarView }
  | { id: string; role: 'assistant'; text: string; envelope?: WidgetEnvelope; executionId?: string; view: SidebarView };

function nextId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function extractExecutionId(response: unknown): string | undefined {
  const item = response as Record<string, unknown>;
  return String(item?.execution_id || item?.executionId || item?.id || '').trim() || undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

// The control plane wraps a step's output several layers deep on the
// getExecution / poll path — e.g. final_result is at
// `event.result.context.result.context.data.{bot_message,render}`. The SSE
// push path delivers it pre-unwrapped (render / bot_message already at the
// top level). Descend through the common {context}/{result}/{data}/
// {output_result} wrappers until we reach the object that actually carries
// the payload, so the #82 reconcile/poll fallback surfaces the real widget +
// bot_message instead of degrading to the "Ready." placeholder with no widget.
function resolvePayloadBag(raw: unknown, depth = 0): Record<string, unknown> | undefined {
  if (!isRecord(raw) || depth > 8) return undefined;
  if (contextHasPayload(raw)) return raw;
  const nested = [
    raw.context,
    isRecord(raw.result) ? raw.result.context : undefined,
    raw.data,
    raw.result,
    raw.output_result,
  ];
  for (const next of nested) {
    const found = resolvePayloadBag(next, depth + 1);
    if (found) return found;
  }
  return undefined;
}

function getEventContext(event: Record<string, unknown>): Record<string, unknown> | undefined {
  const result = event.result as Record<string, unknown> | undefined;
  const outputResult = event.output_result as Record<string, unknown> | undefined;
  const candidates = [result?.context, outputResult?.context, event.context, result, outputResult];
  for (const candidate of candidates) {
    const bag = resolvePayloadBag(candidate);
    if (bag) return bag;
  }
  return candidates.find(isRecord);
}

function contextHasPayload(context: Record<string, unknown>): boolean {
  return Boolean(context.render || context.first_widget || extractEnvelopeFromContext(context) || context.final_slot_state || context.slot_state || context.bot_message);
}

function isWidgetEnvelope(value: unknown): value is WidgetEnvelope {
  if (!isRecord(value)) return false;
  return Boolean(value.schema_version === 1 && value.widget_type && isRecord(value.payload));
}

function extractEnvelopeFromContext(context: Record<string, unknown>): WidgetEnvelope | undefined {
  const data = isRecord(context.data) ? context.data : undefined;
  const event = isRecord(data?.event) ? data.event : undefined;
  const eventPayload = isRecord(event?.payload) ? event.payload : undefined;
  const toolConfig = isRecord(context.tool_config) ? context.tool_config : undefined;
  const toolPayload = isRecord(toolConfig?.payload) ? toolConfig.payload : undefined;
  const argumentsPayload = isRecord(toolPayload?.arguments) ? toolPayload.arguments : undefined;
  const commandEvent = isRecord(argumentsPayload?.event) ? argumentsPayload.event : undefined;
  const commandEventPayload = isRecord(commandEvent?.payload) ? commandEvent.payload : undefined;

  const candidates = [
    context.render,
    context.first_widget,
    eventPayload?.envelope,
    commandEventPayload?.envelope
  ];
  return candidates.find(isWidgetEnvelope);
}

function eventIdRank(event: Record<string, unknown>): string {
  const value = String(event.event_id || '').replace(/\D/g, '');
  return value.padStart(24, '0');
}

function eventPayloadPriority(event: Record<string, unknown>, context: Record<string, unknown>): number {
  const nodeName = String(event.node_name || '');
  const eventType = String(event.event_type || '');
  let priority = 0;
  if (extractEnvelopeFromContext(context)) priority += 200;
  if (nodeName === 'final_result') priority += 100;
  if (eventType === 'workflow.completed' || eventType === 'playbook.completed') priority += 90;
  if (nodeName === 'render_widget_chat') priority += 50;
  if (context.render) priority += 10;
  if (context.first_widget) priority += 5;
  return priority;
}

export function extractPayloadContext(execution: unknown): Record<string, unknown> {
  const item = isRecord(execution) ? execution : {};
  const resolvedResult = resolvePayloadBag(item.result);
  if (resolvedResult) return resolvedResult;

  const resolvedData = resolvePayloadBag(item.data);
  if (resolvedData) return resolvedData;

  let best: { priority: number; eventId: string; context: Record<string, unknown> } | undefined;
  const events = Array.isArray(item.events) ? item.events : [];
  for (const event of events) {
    if (!isRecord(event)) continue;
    const context = getEventContext(event);
    if (!context || !contextHasPayload(context)) continue;
    const priority = eventPayloadPriority(event, context);
    const eventId = eventIdRank(event);
    if (!best || priority > best.priority || (priority === best.priority && eventId > best.eventId)) {
      best = { priority, eventId, context };
    }
  }
  return best?.context || item;
}

export function extractEnvelope(execution: unknown): WidgetEnvelope | undefined {
  const payload = extractPayloadContext(execution);
  const payloadEnvelope = extractEnvelopeFromContext(payload);
  if (payloadEnvelope) return payloadEnvelope;

  const item = isRecord(execution) ? execution : {};
  const events = Array.isArray(item.events) ? item.events : [];
  let best: { priority: number; eventId: string; envelope: WidgetEnvelope } | undefined;
  for (const event of events) {
    if (!isRecord(event)) continue;
    const context = getEventContext(event);
    if (!context) continue;
    const envelope = extractEnvelopeFromContext(context);
    if (!envelope) continue;
    const priority = eventPayloadPriority(event, context);
    const eventId = eventIdRank(event);
    if (!best || priority > best.priority || (priority === best.priority && eventId > best.eventId)) {
      best = { priority, eventId, envelope };
    }
  }
  return best?.envelope;
}

export function extractSlotState(execution: unknown): Record<string, unknown> | undefined {
  const payload = extractPayloadContext(execution);
  const slotState = payload.final_slot_state || payload.slot_state;
  return slotState && typeof slotState === 'object' ? (slotState as Record<string, unknown>) : undefined;
}

export function extractBotMessage(execution: unknown): string {
  const payload = extractPayloadContext(execution);
  return String(payload.bot_message || payload.text || payload.summary || 'Ready.');
}

export function hasFinalPayload(execution: unknown): boolean {
  const payload = extractPayloadContext(execution);
  return Boolean(extractEnvelope(execution) || extractSlotState(execution) || payload.bot_message);
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

// A raw browser fetch rejection ("Load failed" on Safari, "Failed to fetch" /
// "NetworkError" elsewhere) or a bare timeout must never reach the user as its
// cryptic native string — that reads as a silent drop. Map any transport-level
// failure to one actionable, retryable message; pass through the specific,
// meaningful errors (permission denied, a real playbook failure) unchanged.
export function friendlyTurnError(caught: unknown): string {
  const raw = caught instanceof Error ? caught.message : typeof caught === 'string' ? caught : '';
  const transportFailure =
    caught instanceof TypeError ||
    /load failed|failed to fetch|networkerror|network error|timed out|timeout|temporarily unavailable/i.test(raw);
  if (transportFailure) {
    return 'Muno is taking longer than usual and your request did not go through. Tap Retry to try again.';
  }
  return raw || 'Could not submit message';
}

function firstString(...values: unknown[]): string | undefined {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return undefined;
}

function extractExecutionError(execution: unknown, executionId: string, status: string): string {
  const item = execution as Record<string, unknown>;
  const data = item?.data as Record<string, unknown> | undefined;
  const result = item?.result as Record<string, unknown> | undefined;
  const error = item?.error as Record<string, unknown> | string | undefined;
  const dataError = data?.error as Record<string, unknown> | string | undefined;
  const resultError = result?.error as Record<string, unknown> | string | undefined;

  return (
    firstString(
      typeof error === 'string' ? error : error?.message,
      typeof dataError === 'string' ? dataError : dataError?.message,
      typeof resultError === 'string' ? resultError : resultError?.message,
      item?.message,
      data?.message,
      result?.message,
      item?.detail,
      data?.detail,
      result?.detail,
      data?.text,
      result?.text,
      data?.summary,
      result?.summary
    ) || `Execution ${executionId} ${status}`
  );
}

function slotStateFromWidgetEvent(event: WidgetEvent): Record<string, unknown> | undefined {
  const value = event.value as Record<string, unknown> | undefined;
  if (event.action_id?.startsWith('add_place:') && value && typeof value === 'object') {
    const label = String(value.label || value.name || '').trim();
    const id = String(value.id || event.action_id.replace('add_place:', '')).trim();
    if (!label) return undefined;
    return {
      region: {
        label,
        city_code: '',
        country_code: '',
        kind: value.kind || 'city'
      },
      region_label: label,
      region_kind: value.kind || 'city',
      picked_place_id: id,
      places_seen: id ? [id] : []
    };
  }
  return undefined;
}

async function waitForExecution(executionId: string, signal: AbortSignal): Promise<unknown> {
  try {
    const state = await waitForExecutionCompletion(executionId, signal);
    const execution = await getExecution(executionId, signal);
    const status = String((execution as Record<string, unknown>)?.status || '').toLowerCase();
    if (state.event_type === 'playbook.failed' || status === 'failed' || status === 'error' || status === 'cancelled') {
      if (hasFinalPayload(execution)) return execution;
      throw new Error(extractExecutionError(execution, executionId, status || 'failed'));
    }
    return execution;
  } catch (error) {
    if (isAbortError(error)) throw error;
    const execution = await getExecution(executionId, signal);
    const status = String((execution as Record<string, unknown>)?.status || '').toLowerCase();
    if (status === 'failed' || status === 'error' || status === 'cancelled') {
      if (hasFinalPayload(execution)) return execution;
      throw new Error(extractExecutionError(execution, executionId, status));
    }
    return execution;
  }
}

export function ChatThread({
  activeView,
  onSlotStateChange,
  onSummaryChange,
  scrollToMessageId,
  onScrollHandled,
  onViewChange,
  onOpenSidebar,
  onOpenTripState
}: {
  activeView: SidebarView;
  onSlotStateChange?: (slotState: Record<string, unknown>) => void;
  onSummaryChange?: (summary: ChatHistorySummary) => void;
  scrollToMessageId?: string;
  onScrollHandled?: () => void;
  onViewChange?: (view: SidebarView) => void;
  // Mobile-only: when provided, render header buttons that open the
  // sidebar / trip-state drawers. Undefined on desktop (no buttons rendered).
  onOpenSidebar?: () => void;
  onOpenTripState?: () => void;
}) {
  const { t } = useTranslation();
  const auth = useMunoAuth();
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'hello',
      role: 'assistant',
      text: 'Hello from Muno. Tell me where you want to go, and I will build a test-mode itinerary.',
      view: 'searches'
    }
  ]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const threadId = useRef(loadStoredThreadId());
  const activeRequest = useRef<AbortController | null>(null);
  const activeExecutionId = useRef<string | undefined>();
  // The most recent turn's arguments, kept so an actionable error can offer a
  // Retry that re-runs the exact same tap/message instead of losing it.
  const lastTurn = useRef<{ eventType: string; eventPayload: Record<string, unknown>; userText?: string } | undefined>();
  const messageRefs = useRef(new Map<string, HTMLDivElement>());
  const [highlightedId, setHighlightedId] = useState<string | undefined>();

  const visibleMessages = useMemo(
    () =>
      activeView === 'orders'
        ? messages.filter((message) => 'envelope' in message && (message.envelope?.widget_type === 'order_confirmation' || message.envelope?.widget_type === 'hotel_confirmation'))
        : messages,
    [activeView, messages]
  );

  // Derive the sidebar history summary from current messages.
  const summary = useMemo<ChatHistorySummary>(() => {
    const orders: ChatHistorySummary['orders'] = [];
    const searches: ChatHistorySummary['searches'] = [];
    for (const message of messages) {
      if (message.role !== 'assistant' || !('envelope' in message) || !message.envelope) continue;
      const widgetType = message.envelope.widget_type;
      const payload = (message.envelope.payload || {}) as Record<string, unknown>;
      if (widgetType === 'order_confirmation') {
        const ref = String(payload.booking_reference || payload.order_id || 'order');
        const amount = payload.total_amount ? `${payload.total_currency || ''} ${payload.total_amount}`.trim() : '';
        orders.push({
          id: message.id,
          label: `Booking ${ref}`,
          subtitle: amount,
          widgetType
        });
      } else if (widgetType === 'hotel_confirmation') {
        const ref = String(payload.booking_reference || 'booking');
        const amount = payload.total_amount ? `${payload.total_currency || ''} ${payload.total_amount}`.trim() : '';
        orders.push({
          id: message.id,
          label: `Hotel ${ref}`,
          subtitle: [payload.hotel_name, amount].filter(Boolean).join(' · '),
          widgetType
        });
      } else if (widgetType === 'flight_list' || widgetType === 'flight_card') {
        const count = Array.isArray(payload.items) ? `${payload.items.length} options` : 'flight';
        searches.push({ id: message.id, label: 'Flights', subtitle: count, widgetType });
      } else if (widgetType === 'hotel_list' || widgetType === 'hotel_card') {
        const count = Array.isArray(payload.items) ? `${payload.items.length} stays` : 'hotels';
        searches.push({ id: message.id, label: 'Hotels', subtitle: count, widgetType });
      } else if (widgetType === 'place_list' || widgetType === 'place_card') {
        const count = Array.isArray(payload.items) ? `${payload.items.length} places` : 'places';
        searches.push({ id: message.id, label: 'Places', subtitle: count, widgetType });
      } else if (widgetType === 'activity_list') {
        const count = Array.isArray(payload.items) ? `${payload.items.length} activities` : 'activities';
        searches.push({ id: message.id, label: 'Activities', subtitle: count, widgetType });
      } else if (widgetType === 'transfer_list') {
        const count = Array.isArray(payload.items) ? `${payload.items.length} transfers` : 'transfers';
        searches.push({ id: message.id, label: 'Transfers', subtitle: count, widgetType });
      } else if (widgetType === 'itinerary_summary') {
        searches.push({ id: message.id, label: 'Itinerary summary', subtitle: '', widgetType });
      } else if (widgetType === 'calendar_view') {
        searches.push({ id: message.id, label: 'Calendar', subtitle: '', widgetType });
      }
    }
    return { searches, orders, threadId: threadId.current };
  }, [messages]);

  useEffect(() => {
    onSummaryChange?.(summary);
  }, [onSummaryChange, summary]);

  // Scroll to the requested message and highlight it briefly.
  useEffect(() => {
    if (!scrollToMessageId) return;
    const node = messageRefs.current.get(scrollToMessageId);
    if (node) {
      node.scrollIntoView({ behavior: 'smooth', block: 'center' });
      setHighlightedId(scrollToMessageId);
      const timer = window.setTimeout(() => setHighlightedId(undefined), 1500);
      onScrollHandled?.();
      return () => window.clearTimeout(timer);
    }
    onScrollHandled?.();
    return undefined;
  }, [scrollToMessageId, onScrollHandled]);

  const startNewSearch = () => {
    if (submitting) {
      activeRequest.current?.abort();
      activeRequest.current = null;
      activeExecutionId.current = undefined;
      setSubmitting(false);
    }
    clearStoredThreadId();
    threadId.current = loadStoredThreadId();
    setMessages([
      {
        id: 'hello-' + threadId.current,
        role: 'assistant',
        text: 'Hello from Muno. Tell me where you want to go, and I will build a test-mode itinerary.',
        view: 'searches'
      }
    ]);
    setError(undefined);
    setInput('');
    onSlotStateChange?.({});
    onViewChange?.('searches');
  };

  const runTurn = async (eventType: string, eventPayload: Record<string, unknown>, userText?: string) => {
    lastTurn.current = { eventType, eventPayload, userText };
    const controller = new AbortController();
    activeRequest.current?.abort();
    activeRequest.current = controller;
    setError(undefined);
    setSubmitting(true);
    try {
      if (userText) {
        setMessages((current) => [...current, { id: nextId('user'), role: 'user', text: userText, view: 'searches' }]);
      }
      const start = await executePlaybook(
        ITINERARY_PLAYBOOK,
        {
          thread_id: threadId.current,
          event_type: eventType,
          event_payload: eventPayload
        },
        { userUid: auth.user?.sub, signal: controller.signal }
      );
      const executionId = extractExecutionId(start);
      activeExecutionId.current = executionId;
      const execution = hasFinalPayload(start) || !executionId ? start : await waitForExecution(executionId, controller.signal);
      const envelope = extractEnvelope(execution);
      const slotState = extractSlotState(execution);
      if (slotState) {
        onSlotStateChange?.(slotState);
      }
      setMessages((current) => [
        ...current,
        {
          id: nextId('assistant'),
          role: 'assistant',
          text: extractBotMessage(execution),
          envelope,
          executionId,
          view: envelope?.widget_type === 'order_confirmation' || envelope?.widget_type === 'hotel_confirmation' ? 'orders' : 'searches'
        }
      ]);
      // Turn landed — nothing to retry.
      lastTurn.current = undefined;
    } catch (caught) {
      if (isAbortError(caught)) {
        // Caller-initiated cancel/new-turn — not a failure, and not retryable.
        lastTurn.current = undefined;
        setError('Request cancelled. You can send another message.');
      } else {
        // Any other failure keeps lastTurn set so the Retry button can re-run it.
        setError(friendlyTurnError(caught));
      }
    } finally {
      if (activeRequest.current === controller) {
        activeRequest.current = null;
        activeExecutionId.current = undefined;
        setSubmitting(false);
      }
    }
  };

  const submitMessage = () => {
    const text = input.trim();
    if (!text || submitting) return;
    setInput('');
    void runTurn('user_message', { text }, text);
  };

  const handleWidgetEvent = (event: WidgetEvent) => {
    if (submitting) return;
    const optimisticSlotState = slotStateFromWidgetEvent(event);
    if (optimisticSlotState) {
      onSlotStateChange?.(optimisticSlotState);
    }
    void runTurn(event.type === 'widget_submit' ? 'user_widget_submit' : 'user_widget_cta_click', {
      action_id: event.action_id,
      value: event.value,
      submitted_value: event.value
    });
  };

  const retryLastTurn = () => {
    const previous = lastTurn.current;
    if (!previous || submitting) return;
    setError(undefined);
    void runTurn(previous.eventType, previous.eventPayload, previous.userText);
  };

  const cancelRequest = () => {
    const executionId = activeExecutionId.current;
    if (executionId) {
      void cancelExecution(executionId).catch(() => undefined);
    }
    activeRequest.current?.abort();
    activeRequest.current = null;
    activeExecutionId.current = undefined;
    setSubmitting(false);
    setError('Request cancelled. You can send another message.');
  };

  return (
    <Box sx={{ display: 'grid', gridTemplateRows: 'auto 1fr auto', minWidth: 0 }}>
      <Stack
        direction="row"
        alignItems="center"
        spacing={1}
        sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider', bgcolor: 'background.paper' }}
      >
        {onOpenSidebar ? (
          <IconButton edge="start" aria-label="Open menu" onClick={onOpenSidebar} sx={{ mr: 0.5 }}>
            <MenuIcon />
          </IconButton>
        ) : null}
        <Typography variant="h6" noWrap sx={{ flexGrow: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {activeView === 'orders' ? 'Orders' : 'Muno trip planner'}
        </Typography>
        <Tooltip title="Start a new search (clears current thread)">
          <Button
            size="small"
            variant="outlined"
            startIcon={<AddCommentIcon />}
            onClick={startNewSearch}
            sx={{ flexShrink: 0 }}
          >
            New search
          </Button>
        </Tooltip>
        {onOpenTripState ? (
          <Tooltip title="Trip state">
            <IconButton edge="end" aria-label="Open trip state" onClick={onOpenTripState}>
              <LuggageIcon />
            </IconButton>
          </Tooltip>
        ) : null}
      </Stack>
      <Box sx={{ overflow: 'auto', p: 2, display: 'grid', gap: 1.5, alignContent: 'start' }}>
        {activeView === 'orders' && visibleMessages.length === 0 ? (
          <Alert severity="info">No orders yet. Pick a flight and place a Duffel test order to see it here.</Alert>
        ) : null}
        {visibleMessages.map((message) => (
          <Stack
            key={message.id}
            ref={(node) => {
              if (node) messageRefs.current.set(message.id, node);
              else messageRefs.current.delete(message.id);
            }}
            spacing={1}
            alignItems={message.role === 'user' ? 'flex-end' : 'flex-start'}
            sx={{
              transition: 'background-color 400ms ease',
              borderRadius: 1.5,
              p: highlightedId === message.id ? 1 : 0,
              bgcolor: highlightedId === message.id ? 'action.hover' : 'transparent'
            }}
          >
            <Paper
              elevation={message.role === 'user' ? 2 : 0}
              sx={{
                maxWidth: message.role === 'user' ? '70%' : '100%',
                width: message.role === 'assistant' && message.envelope ? 'min(100%, 920px)' : 'auto',
                p: message.role === 'user' ? 1.25 : 0,
                bgcolor: message.role === 'user' ? 'primary.main' : 'transparent',
                color: message.role === 'user' ? 'primary.contrastText' : 'text.primary'
              }}
            >
              {message.role === 'user' ? <Typography variant="body2">{message.text}</Typography> : null}
              {message.role === 'assistant' && message.envelope ? (
                <WidgetRenderer envelope={message.envelope} onWidgetEvent={handleWidgetEvent} />
              ) : message.role === 'assistant' ? (
                <Typography variant="body2">{message.text}</Typography>
              ) : null}
            </Paper>
            {'executionId' in message && message.executionId ? (
              <Typography variant="caption" color="text.secondary">Execution {message.executionId}</Typography>
            ) : null}
          </Stack>
        ))}
        {submitting ? (
          <Stack direction="row" spacing={1} alignItems="center">
            <CircularProgress size={18} />
            <Typography variant="body2" color="text.secondary">Muno is planning...</Typography>
            <Button size="small" variant="outlined" color="inherit" onClick={cancelRequest}>
              Cancel
            </Button>
          </Stack>
        ) : null}
        {error ? (
          <Alert
            severity="error"
            action={
              lastTurn.current && !submitting ? (
                <Button color="inherit" size="small" onClick={retryLastTurn}>
                  Retry
                </Button>
              ) : undefined
            }
          >
            {error}
          </Alert>
        ) : null}
      </Box>
      <Paper
        component="form"
        sx={{ display: 'flex', gap: 1, p: 2, borderRadius: 0 }}
        onSubmit={(event) => {
          event.preventDefault();
          submitMessage();
        }}
      >
        <TextField
          fullWidth
          size="small"
          placeholder={t('chat.placeholder')}
          value={input}
          disabled={submitting}
          onChange={(event) => setInput(event.target.value)}
        />
        <Button variant="contained" type="submit" disabled={submitting || !input.trim()}>
          {t('chat.send')}
        </Button>
      </Paper>
    </Box>
  );
}
