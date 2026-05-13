import axios from 'axios';

export const noetlClient = axios.create({
  baseURL: import.meta.env.VITE_NOETL_API_BASE_URL || '/api',
  timeout: 30000
});

export async function executePlaybook(path: string, workload: Record<string, unknown>) {
  const { data } = await noetlClient.post('/execute', { path, workload });
  return data;
}
