import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { clearSession, storeSession } from './gatewaySession';
import { executePlaybook, noetlClient, waitForExecutionCompletion } from './noetlClient';

class MockEventSource {
  static OPEN = 1;
  static instances: MockEventSource[] = [];
  readyState = MockEventSource.OPEN;
  listeners = new Map<string, Set<(event: MessageEvent) => void>>();
  url: string;

  constructor(url: string) {
    this.url = url;
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

describe('noetlClient auth token handling', () => {
  beforeEach(() => {
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
  });

  afterEach(() => {
    clearSession();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it('attaches the stored gateway session as a Bearer token', async () => {
    const originalAdapter = noetlClient.defaults.adapter;
    storeSession('test-session-token');
    noetlClient.defaults.adapter = async (config) => {
      expect(config.headers.Authorization).toBe('Bearer test-session-token');
      return { data: { ok: true }, status: 200, statusText: 'OK', headers: {}, config };
    };

    await expect(noetlClient.get('/execute')).resolves.toMatchObject({ data: { ok: true } });
    clearSession();
    noetlClient.defaults.adapter = originalAdapter;
  });

  it('adds user_uid to playbook workload when provided', async () => {
    const originalAdapter = noetlClient.defaults.adapter;
    const controller = new AbortController();
    vi.stubEnv('VITE_ALLOW_GUEST', 'true');
    noetlClient.defaults.adapter = async (config) => {
      expect(config.signal).toBe(controller.signal);
      expect(JSON.parse(config.data as string)).toEqual({
        path: 'muno/playbooks/itinerary-planner',
        workload: {
          event_type: 'user_message',
          user_uid: 'auth0|abc'
        }
      });
      return { data: { ok: true }, status: 200, statusText: 'OK', headers: {}, config };
    };

    await expect(
      executePlaybook('muno/playbooks/itinerary-planner', { event_type: 'user_message' }, { userUid: 'auth0|abc', signal: controller.signal })
    ).resolves.toEqual({ ok: true });

    noetlClient.defaults.adapter = originalAdapter;
  });

  it('resolves execution completion from playbook/state SSE frames', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('window', {
      ...globalThis,
      location: { hostname: 'travel.mestumre.dev' }
    });
    vi.stubGlobal('EventSource', MockEventSource);
    MockEventSource.instances = [];
    storeSession('test-session-token');

    const promise = waitForExecutionCompletion('exec-1');
    const source = MockEventSource.instances[0];
    expect(source.url).toContain('/events?session_token=test-session-token');
    source.emit('message', { result: { clientId: 'client-1' } });
    await vi.advanceTimersByTimeAsync(100);
    await Promise.resolve();
    source.emit('playbook/state', {
      jsonrpc: '2.0',
      method: 'playbook/state',
      params: {
        execution_id: 'exec-1',
        event_type: 'playbook.completed',
        status: 'completed',
        at: '2026-05-24T17:00:00Z'
      }
    });

    await expect(promise).resolves.toMatchObject({
      execution_id: 'exec-1',
      event_type: 'playbook.completed',
      status: 'completed'
    });
    vi.useRealTimers();
  });

  it('rejects (does not hang) when the terminal frame never arrives', async () => {
    // Regression: a lifecycle frame routed to a dead SSE client_id is never
    // redelivered. Before the absolute timeout, the waiter hung forever and the
    // "Muno is planning…" spinner never cleared. It must now reject so the
    // caller's poll fallback can recover.
    vi.resetModules();
    vi.useFakeTimers();
    vi.stubGlobal('window', { ...globalThis, location: { hostname: 'travel.mestumre.dev' } });
    vi.stubGlobal('EventSource', MockEventSource);
    MockEventSource.instances = [];
    storeSession('test-session-token');
    const mod = await import('./noetlClient');
    // Keep reconcile from short-circuiting: report the execution as still RUNNING.
    mod.noetlClient.defaults.adapter = async (config) => ({
      data: { status: 'RUNNING' }, status: 200, statusText: 'OK', headers: {}, config
    });

    const promise = mod.waitForExecutionCompletion('exec-stuck');
    const settled = promise.then(() => 'resolved').catch((e: Error) => e.message);
    const source = MockEventSource.instances[0];
    source.emit('message', { result: { clientId: 'client-1' } });
    await vi.advanceTimersByTimeAsync(100);
    // No playbook/state frame is ever emitted (simulating the lost frame).
    await vi.advanceTimersByTimeAsync(180_000);
    await expect(settled).resolves.toBe('Gateway lifecycle confirmation timed out');

    vi.useRealTimers();
  });

  it('recovers a pending turn from a reconnect handshake when its frame was lost', async () => {
    // The SSE dropped mid-turn and the terminal frame was lost in the gap. On
    // reconnect the handshake reconciles in-flight turns by polling status, so
    // the spinner clears without waiting out the absolute timeout.
    vi.resetModules();
    vi.useFakeTimers();
    vi.stubGlobal('window', { ...globalThis, location: { hostname: 'travel.mestumre.dev' } });
    vi.stubGlobal('EventSource', MockEventSource);
    MockEventSource.instances = [];
    storeSession('test-session-token');
    const mod = await import('./noetlClient');
    mod.noetlClient.defaults.adapter = async (config) => ({
      data: { status: 'COMPLETED' }, status: 200, statusText: 'OK', headers: {}, config
    });

    const promise = mod.waitForExecutionCompletion('exec-recover');
    const source = MockEventSource.instances[0];
    // Initial handshake + connection settle so the waiter is registered first
    // (mirrors a turn already in flight).
    source.emit('message', { result: { clientId: 'client-2a' } });
    await vi.advanceTimersByTimeAsync(100);
    // The SSE then dropped and reconnected; the terminal frame was lost in the
    // gap. A reconnect handshake now arrives while the turn is pending — this is
    // what triggers reconciliation (poll status → COMPLETED → resolve).
    source.emit('message', { result: { clientId: 'client-2b' } });
    // Flush the async reconcile (getExecution) without firing the 180s ceiling.
    for (let i = 0; i < 5; i += 1) {
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(1);
    }

    await expect(promise).resolves.toMatchObject({
      execution_id: 'exec-recover',
      event_type: 'playbook.completed',
      status: 'COMPLETED'
    });

    vi.useRealTimers();
  });
});
