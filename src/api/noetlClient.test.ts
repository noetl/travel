import { describe, expect, it } from 'vitest';
import { executePlaybook, noetlClient, setAccessTokenProvider } from './noetlClient';

describe('noetlClient auth token handling', () => {
  it('attaches a Bearer token when a token provider is configured', async () => {
    const originalAdapter = noetlClient.defaults.adapter;
    setAccessTokenProvider(async () => 'test-token');
    noetlClient.defaults.adapter = async (config) => {
      expect(config.headers.Authorization).toBe('Bearer test-token');
      return { data: { ok: true }, status: 200, statusText: 'OK', headers: {}, config };
    };

    await expect(noetlClient.get('/execute')).resolves.toMatchObject({ data: { ok: true } });
    setAccessTokenProvider(undefined);
    noetlClient.defaults.adapter = originalAdapter;
  });

  it('adds user_uid to playbook workload when provided', async () => {
    const originalAdapter = noetlClient.defaults.adapter;
    noetlClient.defaults.adapter = async (config) => {
      expect(JSON.parse(config.data as string)).toEqual({
        path: 'playbooks/itinerary-planner.yaml',
        workload: {
          event_type: 'user_message',
          user_uid: 'auth0|abc'
        }
      });
      return { data: { ok: true }, status: 200, statusText: 'OK', headers: {}, config };
    };

    await expect(
      executePlaybook('playbooks/itinerary-planner.yaml', { event_type: 'user_message' }, { userUid: 'auth0|abc' })
    ).resolves.toEqual({ ok: true });

    noetlClient.defaults.adapter = originalAdapter;
  });
});
