import { describe, expect, it } from 'vitest';
import { friendlyTurnError } from './ChatThread';

// A slow/blipped turn (esp. the pre-execution access-gate or execute fetch)
// must never surface the raw browser fetch string ("Load failed" on Safari,
// "Failed to fetch" elsewhere) — that reads as a silent drop. It maps to one
// actionable, retryable message. Real, meaningful errors pass through so the
// user still learns why (e.g. a permission denial).
describe('friendlyTurnError', () => {
  it('maps Safari "Load failed" to the retryable message', () => {
    expect(friendlyTurnError(new TypeError('Load failed'))).toMatch(/Tap Retry/);
  });

  it('maps "Failed to fetch" to the retryable message', () => {
    expect(friendlyTurnError(new TypeError('Failed to fetch'))).toMatch(/Tap Retry/);
  });

  it('maps a bare NetworkError to the retryable message', () => {
    expect(friendlyTurnError(new Error('NetworkError when attempting to fetch resource'))).toMatch(
      /Tap Retry/
    );
  });

  it('maps a timeout to the retryable message', () => {
    expect(friendlyTurnError(new Error('Gateway lifecycle confirmation timed out'))).toMatch(
      /Tap Retry/
    );
  });

  it('maps the hardened access-gate error to the retryable message', () => {
    expect(friendlyTurnError(new Error('Access check is temporarily unavailable. Please try again.'))).toMatch(
      /Tap Retry/
    );
  });

  it('passes through a permission denial verbatim', () => {
    const msg = 'You do not have permission to execute this playbook';
    expect(friendlyTurnError(new Error(msg))).toBe(msg);
  });

  it('passes through a real playbook failure verbatim', () => {
    const msg = 'Execution 123 failed: provider returned no offers';
    expect(friendlyTurnError(new Error(msg))).toBe(msg);
  });

  it('falls back to a generic message for an empty/unknown error', () => {
    expect(friendlyTurnError(undefined)).toBe('Could not submit message');
  });
});
