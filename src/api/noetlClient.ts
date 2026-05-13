import axios from 'axios';

type AccessTokenProvider = () => Promise<string | null>;

let accessTokenProvider: AccessTokenProvider | undefined;

export const noetlClient = axios.create({
  baseURL: import.meta.env.VITE_NOETL_API_BASE_URL || '/api',
  timeout: 30000
});

noetlClient.interceptors.request.use(async (config) => {
  const token = accessTokenProvider ? await accessTokenProvider() : null;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export function setAccessTokenProvider(provider?: AccessTokenProvider) {
  accessTokenProvider = provider;
}

export async function executePlaybook(
  path: string,
  workload: Record<string, unknown>,
  options: { userUid?: string } = {}
) {
  const body = {
    path,
    workload: options.userUid ? { ...workload, user_uid: options.userUid } : workload
  };
  const { data } = await noetlClient.post('/execute', body);
  return data;
}
