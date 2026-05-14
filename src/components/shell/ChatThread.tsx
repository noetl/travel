import { Alert, Box, Button, CircularProgress, Paper, Stack, TextField, Typography } from '@mui/material';
import { useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { WidgetEnvelope } from '../../contracts/widgets';
import { executePlaybook, getExecution } from '../../api/noetlClient';
import { useMunoAuth } from '../../auth/MunoAuthProvider';
import { WidgetRenderer } from '../WidgetRenderer';
import type { SidebarView } from './Sidebar';
import type { WidgetEvent } from '../widgets/widgetUtils';

const ITINERARY_PLAYBOOK = 'muno/playbooks/itinerary-planner';

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

function extractEnvelope(execution: unknown): WidgetEnvelope | undefined {
  const item = execution as Record<string, unknown>;
  const data = item?.data as Record<string, unknown> | undefined;
  const result = item?.result as Record<string, unknown> | undefined;
  const render = result?.render || data?.render || item?.render;
  if (render && typeof render === 'object' && (render as Record<string, unknown>).widget_type) {
    return render as WidgetEnvelope;
  }
  return undefined;
}

function extractSlotState(execution: unknown): Record<string, unknown> | undefined {
  const item = execution as Record<string, unknown>;
  const data = item?.data as Record<string, unknown> | undefined;
  const result = item?.result as Record<string, unknown> | undefined;
  const slotState = result?.final_slot_state || data?.final_slot_state || result?.slot_state || data?.slot_state;
  return slotState && typeof slotState === 'object' ? (slotState as Record<string, unknown>) : undefined;
}

function extractBotMessage(execution: unknown): string {
  const item = execution as Record<string, unknown>;
  const data = item?.data as Record<string, unknown> | undefined;
  const result = item?.result as Record<string, unknown> | undefined;
  return String(result?.bot_message || data?.bot_message || result?.text || data?.text || result?.summary || data?.summary || item?.status || 'Ready.');
}

function hasFinalPayload(execution: unknown): boolean {
  const item = execution as Record<string, unknown>;
  const data = item?.data as Record<string, unknown> | undefined;
  return Boolean(extractEnvelope(execution) || extractSlotState(execution) || data?.bot_message);
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
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

function abortableDelay(ms: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.reject(new DOMException('Aborted', 'AbortError'));
  return new Promise((resolve, reject) => {
    const timeoutId = window.setTimeout(() => {
      signal.removeEventListener('abort', abort);
      resolve();
    }, ms);
    const abort = () => {
      window.clearTimeout(timeoutId);
      reject(new DOMException('Aborted', 'AbortError'));
    };
    signal.addEventListener('abort', abort, { once: true });
  });
}

async function waitForExecution(executionId: string, signal: AbortSignal): Promise<unknown> {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await abortableDelay(1500, signal);
    const execution = await getExecution(executionId, signal);
    const status = String((execution as Record<string, unknown>)?.status || '').toLowerCase();
    if (status === 'completed' || status === 'succeeded') return execution;
    if (status === 'failed' || status === 'error' || status === 'cancelled') {
      throw new Error(`Execution ${executionId} ${status}`);
    }
  }
  throw new Error(`Execution ${executionId} did not complete in time`);
}

export function ChatThread({
  activeView,
  onSlotStateChange
}: {
  activeView: SidebarView;
  onSlotStateChange?: (slotState: Record<string, unknown>) => void;
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
  const threadId = useRef(`travel-ui-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`);
  const activeRequest = useRef<AbortController | null>(null);

  const visibleMessages = useMemo(
    () =>
      activeView === 'orders'
        ? messages.filter((message) => 'envelope' in message && message.envelope?.widget_type === 'order_confirmation')
        : messages,
    [activeView, messages]
  );

  const runTurn = async (eventType: string, eventPayload: Record<string, unknown>, userText?: string) => {
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
          view: envelope?.widget_type === 'order_confirmation' ? 'orders' : 'searches'
        }
      ]);
    } catch (caught) {
      if (isAbortError(caught)) {
        setError('Request cancelled. You can send another message.');
      } else {
        setError(caught instanceof Error ? caught.message : 'Could not submit message');
      }
    } finally {
      if (activeRequest.current === controller) {
        activeRequest.current = null;
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

  const cancelRequest = () => {
    activeRequest.current?.abort();
    activeRequest.current = null;
    setSubmitting(false);
    setError('Request cancelled. You can send another message.');
  };

  return (
    <Box sx={{ display: 'grid', gridTemplateRows: 'auto 1fr auto', minWidth: 0 }}>
      <Box sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider', bgcolor: 'background.paper' }}>
        <Typography variant="h6">{activeView === 'orders' ? 'Orders' : 'Muno trip planner'}</Typography>
      </Box>
      <Box sx={{ overflow: 'auto', p: 2, display: 'grid', gap: 1.5, alignContent: 'start' }}>
        {activeView === 'orders' && visibleMessages.length === 0 ? (
          <Alert severity="info">No orders yet. Pick a flight and place a Duffel test order to see it here.</Alert>
        ) : null}
        {visibleMessages.map((message) => (
          <Stack key={message.id} spacing={1} alignItems={message.role === 'user' ? 'flex-end' : 'flex-start'}>
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
        {error ? <Alert severity="error">{error}</Alert> : null}
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
