import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { clearSession, storeSession } from './gatewaySession';
import { executePlaybook, noetlClient } from './noetlClient';

describe('noetlClient auth token handling', () => {
  beforeEach(() => {
    const values = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
      clear: () => values.clear()
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
});
