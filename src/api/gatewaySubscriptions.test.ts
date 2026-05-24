import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { clearSession, storeSession } from './gatewaySession';

class MockEventSource {
  static OPEN = 1;
  static instances: MockEventSource[] = [];
  readyState = MockEventSource.OPEN;
  listeners = new Map<string, Set<(event: MessageEvent) => void>>();

  constructor(public url: string) {
    MockEventSource.instances.push(this);
  }

  addEventListener(eventName: string, listener: (event: MessageEvent) => void) {
    const listeners = this.listeners.get(eventName) || new Set();
    listeners.add(listener);
    this.listeners.set(eventName, listeners);
  }

  removeEventListener(eventName: string, listener: (event: MessageEvent) => void) {
    this.listeners.get(eventName)?.delete(listener);
  }

  close() {
    this.readyState = 2;
  }

  emit(eventName: string, data: unknown) {
    for (const listener of this.listeners.get(eventName) || []) {
      listener({ data: JSON.stringify(data) } as MessageEvent);
    }
  }
}

describe('gatewaySubscriptions', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers();
    MockEventSource.instances = [];
    const values = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
      clear: () => values.clear()
    });
    vi.stubGlobal('window', {
      ...globalThis,
      location: { hostname: 'travel.mestumre.dev' }
    });
    vi.stubGlobal('EventSource', MockEventSource);
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes('/api/subscriptions/firestore')) {
          expect(init?.method).toBe('POST');
          expect(init?.headers).toMatchObject({ Authorization: 'Bearer test-session-token' });
          expect(JSON.parse(String(init?.body))).toMatchObject({
            path: 'chat_threads/thread-1/trip/current/events',
            scope: 'owner',
            client_id: 'client-1'
          });
          return new Response(JSON.stringify({ subscription_id: 'sub-1', client_id: 'client-1' }), { status: 200 });
        }
        if (url.includes('/api/subscriptions/sub-1')) {
          return new Response('', { status: 204 });
        }
        return new Response('', { status: 404 });
      })
    );
    storeSession('test-session-token');
  });

  afterEach(() => {
    clearSession();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('coalesces subscription/event frames into sorted document arrays', async () => {
    const { subscribeToCalendarEvents } = await import('./gatewaySubscriptions');
    const onItems = vi.fn();
    const unsubscribe = subscribeToCalendarEvents('chat_threads/thread-1/trip/current/events', onItems);
    const source = MockEventSource.instances[0];
    source.emit('message', { result: { clientId: 'client-1' } });
    await vi.advanceTimersByTimeAsync(100);
    await vi.runAllTimersAsync();

    source.emit('subscription/event', {
      jsonrpc: '2.0',
      method: 'subscription/event',
      params: {
        subscription_id: 'sub-1',
        doc_id: 'evt-2',
        op: 'added',
        data: { start_at: '2026-07-16T09:00:00Z', title: 'Hotel' }
      }
    });
    source.emit('subscription/event', {
      jsonrpc: '2.0',
      method: 'subscription/event',
      params: {
        subscription_id: 'sub-1',
        doc_id: 'evt-1',
        op: 'added',
        data: { start_at: '2026-07-15T08:00:00Z', title: 'Flight' }
      }
    });

    expect(onItems).toHaveBeenLastCalledWith([
      expect.objectContaining({ id: 'evt-1', title: 'Flight' }),
      expect.objectContaining({ id: 'evt-2', title: 'Hotel' })
    ]);

    unsubscribe();
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/subscriptions/sub-1'), expect.objectContaining({ method: 'DELETE' }));
  });
});
