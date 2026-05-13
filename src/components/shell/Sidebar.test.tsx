import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import '../../i18n';
import { SidebarAccount } from './Sidebar';

describe('SidebarAccount', () => {
  it('shows sign in for configured unauthenticated users', () => {
    const html = renderToStaticMarkup(
      <SidebarAccount
        isAuthConfigured
        isAuthenticated={false}
        isLoading={false}
        onLogin={vi.fn()}
        onLogout={vi.fn()}
      />
    );
    expect(html).toContain('Sign in');
    expect(html).toContain('Guest mode');
  });

  it('shows sign out and profile details for authenticated users', () => {
    const html = renderToStaticMarkup(
      <SidebarAccount
        isAuthConfigured
        isAuthenticated
        isLoading={false}
        user={{ name: 'Alex Muno', email: 'alex@example.com', sub: 'auth0|123' }}
        onLogin={vi.fn()}
        onLogout={vi.fn()}
      />
    );
    expect(html).toContain('Alex Muno');
    expect(html).toContain('alex@example.com');
    expect(html).toContain('Sign out');
  });
});
