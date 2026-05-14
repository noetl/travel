import axios from 'axios';
import { clearSession, getGatewayApiBaseUrl, getGatewayBaseUrl, getStoredSession, isGuestAllowed } from './gatewaySession';

let sessionExpiredHandler: (() => void) | undefined;
let eventSource: EventSource | null = null;
let sseConnected = false;
let clientId: string | null = null;
const pendingCallbacks = new Map<
  string,
  {
    resolve: (value: Record<string, unknown>) => void;
    reject: (error: Error) => void;
    timeoutId: number;
  }
>();
const SSE_TIMEOUT_MS = 10_000;
const CALLBACK_TIMEOUT_MS = 120_000;

export const noetlClient = axios.create({
  baseURL: getGatewayApiBaseUrl(),
  timeout: 30000
});

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

async function checkPlaybookAccess(playbookPath: string, token: string): Promise<boolean> {
  const response = await fetch(`${getGatewayBaseUrl()}/api/auth/check-access`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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
    const error = params.error as { message?: string } | undefined;
    pending.reject(new Error(error?.message || 'Playbook execution failed'));
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

function connectSSE(token: string): void {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }

  const url =
    `${getGatewayBaseUrl()}/events?session_token=${encodeURIComponent(token)}` +
    (clientId ? `&client_id=${encodeURIComponent(clientId)}` : '');
  eventSource = new EventSource(url);

  eventSource.addEventListener('message', (event) => {
    try {
      const message = JSON.parse(event.data);
      if (message?.result?.clientId) {
        clientId = message.result.clientId;
        sseConnected = true;
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

  eventSource.onerror = () => {
    sseConnected = false;
  };
}

async function waitForSSEConnection(token: string): Promise<void> {
  if (sseConnected && eventSource?.readyState === EventSource.OPEN) return;

  return new Promise((resolve, reject) => {
    const timeoutId = window.setTimeout(() => {
      unsubscribe();
      reject(new Error('Gateway callback connection timed out'));
    }, SSE_TIMEOUT_MS);

    const intervalId = window.setInterval(() => {
      if (sseConnected && eventSource?.readyState === EventSource.OPEN) {
        unsubscribe();
        resolve();
      }
    }, 100);

    const unsubscribe = () => {
      window.clearTimeout(timeoutId);
      window.clearInterval(intervalId);
    };

    connectSSE(token);
  });
}

function waitForPlaybookCallback(requestId: string): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    const timeoutId = window.setTimeout(() => {
      pendingCallbacks.delete(requestId);
      reject(new Error('Playbook callback timed out'));
    }, CALLBACK_TIMEOUT_MS);
    pendingCallbacks.set(requestId, { resolve, reject, timeoutId });
  });
}

async function executeViaGatewayGraphQL(path: string, workload: Record<string, unknown>, token: string) {
  const hasAccess = await checkPlaybookAccess(path, token);
  if (!hasAccess) {
    throw new Error('You do not have permission to execute this playbook');
  }

  await waitForSSEConnection(token);

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
    body: JSON.stringify({
      query: mutation,
      variables: { name: path, vars: workload, clientId }
    })
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
    return waitForPlaybookCallback(execution.requestId);
  }
  return execution;
}

async function executeDirect(path: string, workload: Record<string, unknown>) {
  const { data } = await noetlClient.post('/execute', { path, workload });
  return data;
}

export async function executePlaybook(
  path: string,
  workload: Record<string, unknown>,
  options: { userUid?: string } = {}
) {
  const finalWorkload = options.userUid ? { ...workload, user_uid: options.userUid } : workload;
  const session = getStoredSession();
  if (session?.token) {
    return executeViaGatewayGraphQL(path, finalWorkload, session.token);
  }
  if (isGuestAllowed()) {
    return executeDirect(path, finalWorkload);
  }
  throw new Error('Sign in is required before executing playbooks');
}

export async function getExecution(id: string) {
  const { data } = await noetlClient.get(`/executions/${id}`, { params: { page_size: 20 } });
  return data;
}
