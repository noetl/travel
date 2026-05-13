import { Avatar, Box, Button, Divider, List, ListItemButton, ListItemText, Stack, Typography } from '@mui/material';
import { useTranslation } from 'react-i18next';
import { useMunoAuth, type MunoUser } from '../../auth/MunoAuthProvider';

export type SidebarView = 'searches' | 'orders';

export function SidebarAccount({
  isAuthConfigured,
  isAuthenticated,
  isLoading,
  user,
  onLogin,
  onLogout
}: {
  isAuthConfigured: boolean;
  isAuthenticated: boolean;
  isLoading: boolean;
  user?: MunoUser;
  onLogin: () => void;
  onLogout: () => void;
}) {
  const { t } = useTranslation();
  if (isLoading) {
    return <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>{t('auth.loading')}</Typography>;
  }

  if (isAuthenticated) {
    return (
      <Stack spacing={1.25} sx={{ mb: 2 }}>
        <Stack direction="row" spacing={1} alignItems="center">
          <Avatar src={user?.picture} alt={user?.name || user?.email || 'User'} sx={{ width: 34, height: 34 }}>
            {(user?.name || user?.email || 'U').slice(0, 1).toUpperCase()}
          </Avatar>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="body2" fontWeight={700} noWrap>
              {user?.name || user?.email || t('sidebar.signed_in')}
            </Typography>
            <Typography variant="caption" color="text.secondary" noWrap>
              {user?.email || user?.sub}
            </Typography>
          </Box>
        </Stack>
        <Button size="small" variant="outlined" onClick={onLogout}>{t('sidebar.signout')}</Button>
      </Stack>
    );
  }

  return (
    <Stack spacing={1} sx={{ mb: 2 }}>
      <Typography variant="body2" color="text.secondary">
        {isAuthConfigured ? t('sidebar.guest') : t('sidebar.auth_unconfigured')}
      </Typography>
      <Button size="small" variant="contained" onClick={onLogin} disabled={!isAuthConfigured}>
        {t('sidebar.signin')}
      </Button>
    </Stack>
  );
}

export function Sidebar({ activeView, onViewChange }: { activeView: SidebarView; onViewChange: (view: SidebarView) => void }) {
  const { t } = useTranslation();
  const auth = useMunoAuth();
  return (
    <Box sx={{ borderRight: '1px solid', borderColor: 'divider', bgcolor: 'background.paper', p: 2 }}>
      <Typography variant="h5" sx={{ mb: 2 }}>{t('app_name')}</Typography>
      <SidebarAccount
        isAuthConfigured={auth.isAuthConfigured}
        isAuthenticated={auth.isAuthenticated}
        isLoading={auth.isLoading}
        user={auth.user}
        onLogin={() => void auth.login()}
        onLogout={auth.logout}
      />
      <Divider />
      <List dense>
        <ListItemButton selected={activeView === 'searches'} onClick={() => onViewChange('searches')}>
          <ListItemText primary={t('sidebar.searches')} />
        </ListItemButton>
        <ListItemButton selected={activeView === 'orders'} onClick={() => onViewChange('orders')}>
          <ListItemText primary={t('sidebar.orders')} />
        </ListItemButton>
      </List>
    </Box>
  );
}
