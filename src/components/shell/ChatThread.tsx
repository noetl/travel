import { Alert, Box, Button, CircularProgress, Paper, Stack, TextField, Typography } from '@mui/material';
import { useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { WidgetEnvelope } from '../../contracts/widgets';
import { executePlaybook, getExecution } from '../../api/noetlClient';
import { useMunoAuth } from '../../auth/MunoAuthProvider';
import { WidgetRenderer } from '../WidgetRenderer';
import type { SidebarView } from './Sidebar';
import type { WidgetEvent } from '../widgets/widgetUtils';

const ITINERARY_PLAYBOOK = 'playbooks/itinerary-planner.yaml';

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
  const result = item?.result as Record<string, unknown> | undefined;
  const render = result?.render || item?.render;
  if (render && typeof render === 'object' && (render as Record<string, unknown>).widget_type) {
    return render as WidgetEnvelope;
  }
  return undefined;
}

function extractBotMessage(execution: unknown): string {
  const item = execution as Record<string, unknown>;
  const result = item?.result as Record<string, unknown> | undefined;
  return String(result?.bot_message || result?.text || result?.summary || item?.status || 'Ready.');
}

async function waitForExecution(executionId: string): Promise<unknown> {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 1500));
    const execution = await getExecution(executionId);
    const status = String((execution as Record<string, unknown>)?.status || '').toLowerCase();
    if (status === 'completed' || status === 'succeeded') return execution;
    if (status === 'failed' || status === 'error' || status === 'cancelled') {
      throw new Error(`Execution ${executionId} ${status}`);
    }
  }
  throw new Error(`Execution ${executionId} did not complete in time`);
}

export function ChatThread({ activeView }: { activeView: SidebarView }) {
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

  const visibleMessages = useMemo(
    () =>
      activeView === 'orders'
        ? messages.filter((message) => 'envelope' in message && message.envelope?.widget_type === 'order_confirmation')
        : messages,
    [activeView, messages]
  );

  const runTurn = async (eventType: string, eventPayload: Record<string, unknown>, userText?: string) => {
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
        { userUid: auth.user?.sub }
      );
      const executionId = extractExecutionId(start);
      const execution = executionId ? await waitForExecution(executionId) : start;
      const envelope = extractEnvelope(execution);
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
      setError(caught instanceof Error ? caught.message : 'Could not submit message');
    } finally {
      setSubmitting(false);
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
    void runTurn(event.type === 'widget_submit' ? 'user_widget_submit' : 'user_widget_cta_click', {
      action_id: event.action_id,
      value: event.value,
      submitted_value: event.value
    });
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
