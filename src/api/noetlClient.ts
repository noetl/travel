import axios from 'axios';
import { clearSession, getGatewayApiBaseUrl, getGatewayBaseUrl, getStoredSession, isGuestAllowed } from './gatewaySession';

let sessionExpiredHandler: (() => void) | undefined;

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

async function executeViaGatewayGraphQL(path: string, workload: Record<string, unknown>, token: string) {
  const hasAccess = await checkPlaybookAccess(path, token);
  if (!hasAccess) {
    throw new Error('You do not have permission to execute this playbook');
  }

  const mutation = `
    mutation ExecutePlaybook($name: String!, $vars: JSON) {
      executePlaybook(name: $name, variables: $vars) {
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
      variables: { name: path, vars: workload }
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
  return body.data?.executePlaybook;
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
