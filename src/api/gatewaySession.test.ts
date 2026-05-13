import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { clearSession, loginToGateway } from './gatewaySession';

describe('gatewaySession', () => {
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
    vi.useRealTimers();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it('times out a stalled gateway login request', async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      'fetch',
      vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
        });
      })
    );

    const request = expect(loginToGateway('test-id-token', 'mestumre-development.us.auth0.com')).rejects.toThrow(
      'Gateway auth request timed out after 15s'
    );
    await vi.advanceTimersByTimeAsync(15_000);

    await request;
  });
});
