import { describe, expect, it } from 'vitest';
import { withSubject } from './MunoAuthProvider';

describe('withSubject', () => {
  it('takes auth0_id from the gateway user payload (noetl/server#533)', () => {
    expect(withSubject({ email: 'a@b.c', auth0_id: 'auth0|abc' })?.sub).toBe('auth0|abc');
  });

  it('falls back to the ID-token subject when the payload has neither', () => {
    expect(withSubject({ email: 'a@b.c' }, 'auth0|tok')?.sub).toBe('auth0|tok');
  });

  it('keeps an explicit sub', () => {
    expect(withSubject({ sub: 'auth0|s', auth0_id: 'auth0|other' }, 'auth0|tok')?.sub).toBe('auth0|s');
  });

  it('leaves a user with no known subject without one', () => {
    expect(withSubject({ email: 'a@b.c' })?.sub).toBeUndefined();
    expect(withSubject(undefined, 'auth0|tok')).toBeUndefined();
  });
});
