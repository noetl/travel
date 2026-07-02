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

  it('retries once then times out a persistently stalled gateway login request', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    const request = expect(loginToGateway('test-id-token', 'mestumre-development.us.auth0.com')).rejects.toThrow(
      'Gateway auth request timed out after 40s'
    );
    // First 40s attempt aborts, the client retries, the second 40s attempt aborts.
    await vi.advanceTimersByTimeAsync(80_000);

    await request;
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('silently retries a timed-out login and succeeds on the second attempt', async () => {
    vi.useFakeTimers();
    let call = 0;
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      call += 1;
      if (call === 1) {
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
        });
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({ session_token: 'tok', user: { email: 'a@b.c' } })
      } as unknown as Response);
    });
    vi.stubGlobal('fetch', fetchMock);

    const request = loginToGateway('test-id-token', 'mestumre-development.us.auth0.com');
    // First attempt aborts at 40s; the retry resolves immediately.
    await vi.advanceTimersByTimeAsync(40_000);

    const result = await request;
    expect(result.sessionToken).toBe('tok');
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
