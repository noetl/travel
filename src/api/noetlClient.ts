import axios from 'axios';
import { clearSession, getGatewayApiBaseUrl, getGatewayBaseUrl, getStoredSession, isGuestAllowed } from './gatewaySession';

let sessionExpiredHandler: (() => void) | undefined;
let eventSource: EventSource | null = null;
let sseConnected = false;
let clientId: string | null = null;
const sseListeners = new Map<string, Set<(event: MessageEvent) => void>>();
const pendingCallbacks = new Map<
  string,
  {
    resolve: (value: Record<string, unknown>) => void;
    reject: (error: Error) => void;
    timeoutId: number;
  }
>();
const pendingExecutionStates = new Map<
  string,
  {
    resolve: (value: PlaybookStateEvent) => void;
    reject: (error: Error) => void;
    timeoutId?: number;
  }
>();
const SSE_TIMEOUT_MS = 10_000;
const CALLBACK_TIMEOUT_MS = 120_000;
const SSE_DROP_GRACE_MS = 15_000;
// Absolute ceiling on waiting for a turn's terminal lifecycle frame. The
// gateway routes `playbook/state` / `playbook/result` frames to a specific
// SSE `client_id`; if the connection that turn's callback was bound to closes
// during a reconnect gap, the hub has no live channel and the frame is dropped
// with NO redelivery. Without a ceiling the pending entry waits forever and the
// "Muno is planning…" spinner never clears. On expiry we reject so the caller's
// poll fallback (`getExecution`) recovers the result instead of hanging.
const EXECUTION_STATE_TIMEOUT_MS = 180_000;

export interface PlaybookStateEvent {
  execution_id: string;
  event_type: string;
  step_name?: string;
  status?: string;
  at?: string;
  error?: unknown;
}

export const noetlClient = axios.create({
  baseURL: getGatewayApiBaseUrl(),
  timeout: 30000
});

function getNoetlApiBaseUrl(): string {
  return getStoredSession()?.token ? `${getGatewayBaseUrl()}/noetl` : getGatewayApiBaseUrl();
}

noetlClient.interceptors.request.use((config) => {
  const session = getStoredSession();
  if (session?.token) {
    config.headers.Authorization = `Bearer ${session.token}`;
  }
  return config;
});

noetlClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      clearSession();
      sessionExpiredHandler?.();
    }
    return Promise.reject(error);
  }
);

export function setSessionExpiredHandler(handler?: () => void) {
  sessionExpiredHandler = handler;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) {
    throw new DOMException('Aborted', 'AbortError');
  }
}

async function checkPlaybookAccess(playbookPath: string, token: string, signal?: AbortSignal): Promise<boolean> {
  const response = await fetch(`${getGatewayBaseUrl()}/api/auth/check-access`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal,
    body: JSON.stringify({
      session_token: token,
      playbook_path: playbookPath,
      permission_type: 'execute'
    })
  });

  if (!response.ok) return false;
  const data = (await response.json()) as { allowed?: boolean };
  return Boolean(data.allowed);
}

function handlePlaybookResult(message: unknown) {
  const params = ((message as Record<string, unknown>)?.params || {}) as Record<string, unknown>;
  const requestId = String(params.requestId || '');
  if (!requestId) return;

  const pending = pendingCallbacks.get(requestId);
  if (!pending) return;

  pendingCallbacks.delete(requestId);
  window.clearTimeout(pending.timeoutId);

  if (params.status === 'FAILED' || params.error) {
    pending.resolve({
      id: params.executionId,
      executionId: params.executionId,
      requestId,
      status: params.status,
      error: params.error,
      data: (params.data || {}) as Record<string, unknown>
    });
    return;
  }

  pending.resolve({
    id: params.executionId,
    executionId: params.executionId,
    requestId,
    status: params.status,
    data: (params.data || {}) as Record<string, unknown>
  });
}

function handlePlaybookState(message: unknown) {
  const params = ((message as Record<string, unknown>)?.params || {}) as Record<string, unknown>;
  const executionId = String(params.execution_id || params.executionId || '').trim();
  const eventType = String(params.event_type || params.eventType || '').trim();
  if (!executionId || !eventType) return;
  if (eventType !== 'playbook.completed' && eventType !== 'playbook.failed') return;

  const pending = pendingExecutionStates.get(executionId);
  if (!pending) return;

  pendingExecutionStates.delete(executionId);
  if (pending.timeoutId !== undefined) window.clearTimeout(pending.timeoutId);
  pending.resolve({
    execution_id: executionId,
    event_type: eventType,
    step_name: typeof params.step_name === 'string' ? params.step_name : undefined,
    status: typeof params.status === 'string' ? params.status : undefined,
    at: typeof params.at === 'string' ? params.at : undefined,
    error: params.error
  });
}

// Resolve any pending execution waiters whose terminal lifecycle frame may
// have been lost (e.g. dropped during an SSE reconnect gap) by polling the
// authoritative execution status. Best-effort: failures leave the pending
// entry in place so the absolute timeout remains the backstop.
async function reconcilePendingExecutions(): Promise<void> {
  const executionIds = Array.from(pendingExecutionStates.keys());
  for (const executionId of executionIds) {
    const pending = pendingExecutionStates.get(executionId);
    if (!pending) continue;
    try {
      const execution = (await getExecution(executionId)) as Record<string, unknown>;
      const status = String(execution?.status || '').toUpperCase();
      if (status === 'COMPLETED' || status === 'FAILED' || status === 'ERROR' || status === 'CANCELLED') {
        pendingExecutionStates.delete(executionId);
        if (pending.timeoutId !== undefined) window.clearTimeout(pending.timeoutId);
        pending.resolve({
          execution_id: executionId,
          event_type: status === 'COMPLETED' ? 'playbook.completed' : 'playbook.failed',
          status
        });
      }
    } catch {
      // Best-effort recovery; the absolute timeout still bounds the wait.
    }
  }
}

function attachRegisteredListeners(source: EventSource) {
  for (const [eventName, listeners] of sseListeners) {
    for (const listener of listeners) {
      source.addEventListener(eventName, listener as EventListener);
    }
  }
}

function connectSSE(token: string): void {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }

  const url =
    `${getGatewayBaseUrl()}/events?session_token=${encodeURIComponent(token)}` +
    (clientId ? `&client_id=${encodeURIComponent(clientId)}` : '');
  eventSource = new EventSource(url);
  attachRegisteredListeners(eventSource);

  eventSource.addEventListener('message', (event) => {
    try {
      const message = JSON.parse(event.data);
      if (message?.result?.clientId) {
        clientId = message.result.clientId;
        sseConnected = true;
        // A (re)connect handshake just landed. Any turn whose terminal frame
        // was dropped while the previous connection was down would otherwise
        // hang until EXECUTION_STATE_TIMEOUT_MS. Reconcile in-flight turns by
        // polling their authoritative status so a recovered connection clears
        // the spinner promptly instead of waiting out the ceiling.
        void reconcilePendingExecutions();
      }
    } catch {
      // Ignore heartbeat/noise frames.
    }
  });

  eventSource.addEventListener('playbook/result', (event) => {
    try {
      handlePlaybookResult(JSON.parse(event.data));
    } catch {
      // Ignore malformed result frames.
    }
  });

  eventSource.addEventListener('playbook/state', (event) => {
    try {
      handlePlaybookState(JSON.parse(event.data));
    } catch {
      // Ignore malformed lifecycle frames.
    }
  });

  eventSource.onerror = () => {
    sseConnected = false;
    for (const [executionId, pending] of pendingExecutionStates) {
      if (pending.timeoutId !== undefined) window.clearTimeout(pending.timeoutId);
      const timeoutId = window.setTimeout(() => {
        pendingExecutionStates.delete(executionId);
        pending.reject(new Error('Gateway lifecycle stream disconnected'));
      }, SSE_DROP_GRACE_MS);
      pendingExecutionStates.set(executionId, { ...pending, timeoutId });
    }
  };
}

export async function ensureGatewaySSE(signal?: AbortSignal): Promise<{ token: string; clientId: string }> {
  const token = getStoredSession()?.token;
  if (!token) throw new Error('Sign in is required before subscribing to gateway events');
  await waitForSSEConnection(token, signal);
  if (!clientId) throw new Error('Gateway callback connection did not return a client id');
  return { token, clientId };
}

export function addGatewaySSEListener(eventName: string, listener: (event: MessageEvent) => void): () => void {
  const listeners = sseListeners.get(eventName) || new Set();
  listeners.add(listener);
  sseListeners.set(eventName, listeners);
  eventSource?.addEventListener(eventName, listener as EventListener);

  return () => {
    listeners.delete(listener);
    if (!listeners.size) {
      sseListeners.delete(eventName);
    }
    eventSource?.removeEventListener(eventName, listener as EventListener);
  };
}

async function waitForSSEConnection(token: string, signal?: AbortSignal): Promise<void> {
  if (sseConnected && eventSource?.readyState === EventSource.OPEN && clientId) return;
  throwIfAborted(signal);

  return new Promise((resolve, reject) => {
    const timeoutId = window.setTimeout(() => {
      unsubscribe();
      reject(new Error('Gateway callback connection timed out'));
    }, SSE_TIMEOUT_MS);

    const abort = () => {
      unsubscribe();
      reject(new DOMException('Aborted', 'AbortError'));
    };

    const intervalId = window.setInterval(() => {
      if (sseConnected && eventSource?.readyState === EventSource.OPEN && clientId) {
        unsubscribe();
        resolve();
      }
    }, 100);

    const unsubscribe = () => {
      window.clearTimeout(timeoutId);
      window.clearInterval(intervalId);
      signal?.removeEventListener('abort', abort);
    };

    signal?.addEventListener('abort', abort, { once: true });
    connectSSE(token);
  });
}

export async function waitForExecutionCompletion(executionId: string, signal?: AbortSignal): Promise<PlaybookStateEvent> {
  throwIfAborted(signal);
  await ensureGatewaySSE(signal);
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      const pending = pendingExecutionStates.get(executionId);
      if (pending) {
        window.clearTimeout(pending.timeoutId);
        pendingExecutionStates.delete(executionId);
      }
      signal?.removeEventListener('abort', abort);
    };
    const abort = () => {
      cleanup();
      reject(new DOMException('Aborted', 'AbortError'));
    };
    // Absolute ceiling: a terminal frame routed to a now-dead SSE client_id is
    // never redelivered, so without this the waiter (and the spinner) hangs
    // forever. On expiry reject; the caller's poll fallback recovers the result.
    const timeoutId = window.setTimeout(() => {
      pendingExecutionStates.delete(executionId);
      signal?.removeEventListener('abort', abort);
      reject(new Error('Gateway lifecycle confirmation timed out'));
    }, EXECUTION_STATE_TIMEOUT_MS);
    pendingExecutionStates.set(executionId, { resolve, reject, timeoutId });
    signal?.addEventListener('abort', abort, { once: true });
  });
}

function waitForPlaybookCallback(
  requestId: string,
  signal?: AbortSignal,
  timeoutMs = CALLBACK_TIMEOUT_MS
): Promise<Record<string, unknown>> {
  throwIfAborted(signal);
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      const pending = pendingCallbacks.get(requestId);
      if (pending) {
        window.clearTimeout(pending.timeoutId);
        pendingCallbacks.delete(requestId);
      }
      signal?.removeEventListener('abort', abort);
    };
    const abort = () => {
      cleanup();
      reject(new DOMException('Aborted', 'AbortError'));
    };
    const timeoutId = window.setTimeout(() => {
      signal?.removeEventListener('abort', abort);
      pendingCallbacks.delete(requestId);
      reject(new Error('Playbook callback timed out'));
    }, timeoutMs);
    pendingCallbacks.set(requestId, {
      resolve: (value) => {
        signal?.removeEventListener('abort', abort);
        resolve(value);
      },
      reject: (error) => {
        signal?.removeEventListener('abort', abort);
        reject(error);
      },
      timeoutId
    });
    signal?.addEventListener('abort', abort, { once: true });
  });
}

function getExecutionId(execution: Record<string, unknown>): string {
  return String(execution.executionId || execution.execution_id || execution.id || '').trim();
}

function callbackFallback(execution: Record<string, unknown>, requestId: string): Record<string, unknown> {
  const executionId = getExecutionId(execution);
  return {
    ...execution,
    id: executionId || execution.id,
    executionId: executionId || execution.executionId,
    execution_id: executionId || execution.execution_id,
    requestId,
    status: execution.status || 'started',
    callbackTimedOut: true
  };
}

async function executeViaGatewayGraphQL(path: string, workload: Record<string, unknown>, token: string, signal?: AbortSignal) {
  const hasAccess = await checkPlaybookAccess(path, token, signal);
  if (!hasAccess) {
    throw new Error('You do not have permission to execute this playbook');
  }

  try {
    await waitForSSEConnection(token, signal);
  } catch (error) {
    if (isAbortError(error)) throw error;
    // The execution id returned by GraphQL is enough for status polling. Do not
    // block a user turn just because the browser callback channel is unavailable.
    sseConnected = false;
  }

  const mutation = `
    mutation ExecutePlaybook($name: String!, $vars: JSON, $clientId: String) {
      executePlaybook(name: $name, variables: $vars, clientId: $clientId) {
        id
        executionId
        requestId
        name
        status
      }
    }
  `;

  const response = await fetch(`${getGatewayBaseUrl()}/graphql`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`
    },
    signal,
    body: JSON.stringify({
      query: mutation,
      variables: { name: path, vars: workload, clientId }
    })
  }).catch((error) => {
    if (isAbortError(error)) {
      throw new DOMException('Aborted', 'AbortError');
    }
    throw error;
  });

  if (response.status === 401) {
    clearSession();
    sessionExpiredHandler?.();
    throw new Error('Session expired');
  }
  if (!response.ok) {
    throw new Error(`GraphQL request failed (${response.status})`);
  }

  const body = await response.json();
  if (body.errors?.length) {
    throw new Error(body.errors[0].message || 'GraphQL error');
  }
  const execution = body.data?.executePlaybook || {};
  if (execution.requestId) {
    const requestId = String(execution.requestId);
    const executionId = getExecutionId(execution);
    if (executionId) {
      return callbackFallback(execution, requestId);
    }
    try {
      return await waitForPlaybookCallback(requestId, signal, CALLBACK_TIMEOUT_MS);
    } catch (error) {
      if (isAbortError(error)) throw error;
      throw error;
    }
  }
  return execution;
}

async function executeDirect(path: string, workload: Record<string, unknown>, signal?: AbortSignal) {
  const { data } = await noetlClient.post('/execute', { path, workload }, { signal });
  return data;
}

export async function executePlaybook(
  path: string,
  workload: Record<string, unknown>,
  options: { userUid?: string; signal?: AbortSignal } = {}
) {
  const finalWorkload = options.userUid ? { ...workload, user_uid: options.userUid } : workload;
  const session = getStoredSession();
  if (session?.token) {
    return executeViaGatewayGraphQL(path, finalWorkload, session.token, options.signal);
  }
  if (isGuestAllowed()) {
    return executeDirect(path, finalWorkload, options.signal);
  }
  throw new Error('Sign in is required before executing playbooks');
}

export async function getExecution(id: string, signal?: AbortSignal) {
  const { data } = await noetlClient.get(`/executions/${id}`, {
    baseURL: getNoetlApiBaseUrl(),
    // Widget payloads are emitted before the terminal final_result event. A
    // small event page can contain the final bot text but miss the full
    // append_widget_event envelope, leaving the UI with text only.
    params: { page_size: 100 },
    signal
  });
  return data;
}

export async function cancelExecution(id: string, signal?: AbortSignal) {
  const { data } = await noetlClient.post(
    `/executions/${id}/cancel`,
    { reason: 'Cancelled from Muno UI', cascade: true },
    { baseURL: getNoetlApiBaseUrl(), signal }
  );
  return data;
}
