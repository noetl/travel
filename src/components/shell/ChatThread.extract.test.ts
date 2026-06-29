import { describe, expect, it } from 'vitest';
import {
  extractBotMessage,
  extractEnvelope,
  hasFinalPayload,
} from './ChatThread';

// Mirrors the real getExecution / poll (#82 reconcile) shape from prod exec
// 330004004241154048: the final_result payload is nested under a double
// `result.context` wrapper — event.result.context.result.context.data.{...}.
// Before the fix the extract helpers only looked one level deep, so
// contextHasPayload was false, the event was skipped, and extractBotMessage
// returned the literal "Ready." with no widget.
function nestedExecution(bag: Record<string, unknown>) {
  return {
    execution_id: '330004004241154048',
    status: 'COMPLETED',
    events: [
      {
        event_id: '330004004555726848',
        node_name: 'normalize_input',
        event_type: 'call.done',
        result: { context: { result: { context: { data: { thread_path: 't' } } } } },
      },
      {
        event_id: '330004062101577728',
        node_name: 'final_result',
        event_type: 'call.done',
        result: {
          context: {
            call_index: 0,
            command_id: '330004004241154048:final_result',
            result: {
              context: {
                data: bag,
                duration_ms: 173,
                exit_code: 0,
                status: 'success',
                stdout: '',
              },
              status: 'success',
            },
          },
        },
        status: 'COMPLETED',
      },
    ],
  };
}

const datePicker = {
  schema_version: 1,
  variant: 'compact',
  widget_type: 'date_range_picker',
  payload: { min_date: '2026-06-29', max_date: '2027-06-29', submit: 'submit' },
};

const placeList = {
  schema_version: 1,
  variant: 'default',
  widget_type: 'place_list',
  payload: { title: 'Places to start from', items: [{ place_id: 'ChIJD7fiBh9u5kcRYJSMaMOCCwQ', name: 'Paris' }] },
};

describe('ChatThread payload extraction (getExecution reconcile path)', () => {
  it('surfaces the real bot_message from the deeply nested final_result, not "Ready."', () => {
    const exec = nestedExecution({
      bot_message: 'Pick the travel dates.',
      render: datePicker,
      final_slot_state: { region: { label: 'Paris' } },
    });
    expect(extractBotMessage(exec)).toBe('Pick the travel dates.');
    expect(extractBotMessage(exec)).not.toBe('Ready.');
  });

  it('surfaces the actual widget envelope (date_range_picker) from the nested payload', () => {
    const exec = nestedExecution({ bot_message: 'Pick the travel dates.', render: datePicker });
    const env = extractEnvelope(exec);
    expect(env?.widget_type).toBe('date_range_picker');
  });

  it('surfaces a place_list widget with its real items', () => {
    const exec = nestedExecution({
      bot_message: 'I found a destination anchor. Next I need dates and travellers.',
      render: placeList,
    });
    const env = extractEnvelope(exec);
    expect(env?.widget_type).toBe('place_list');
    expect((env?.payload as { items: unknown[] }).items).toHaveLength(1);
    expect(extractBotMessage(exec)).toContain('destination anchor');
  });

  it('hasFinalPayload is true once the nested final_result is present', () => {
    const exec = nestedExecution({ bot_message: 'Pick the travel dates.', render: datePicker });
    expect(hasFinalPayload(exec)).toBe(true);
  });

  it('falls back to "Ready." only when there is genuinely no payload anywhere', () => {
    const empty = { execution_id: 'x', status: 'RUNNING', events: [] };
    expect(extractBotMessage(empty)).toBe('Ready.');
    expect(hasFinalPayload(empty)).toBe(false);
  });

  it('still reads a pre-unwrapped (SSE push) payload at the top level', () => {
    const sse = { result: { render: datePicker, bot_message: 'Pick the travel dates.' } };
    expect(extractBotMessage(sse)).toBe('Pick the travel dates.');
    expect(extractEnvelope(sse)?.widget_type).toBe('date_range_picker');
  });
});
