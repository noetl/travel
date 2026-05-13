import { Alert, Box, Button, CircularProgress, Stack, Typography } from '@mui/material';
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMunoAuth } from './MunoAuthProvider';

export function AuthCallback() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { isAuthConfigured, isLoading, canUseApp, gatewayError, login } = useMunoAuth();

  useEffect(() => {
    if (!isLoading && canUseApp) navigate('/', { replace: true });
  }, [canUseApp, isLoading, navigate]);

  if (!isAuthConfigured) {
    return (
      <Box sx={{ p: 4 }}>
        <Alert severity="warning">{t('auth.not_configured')}</Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
      <Stack spacing={2} alignItems="center" sx={{ textAlign: 'center' }}>
        {gatewayError ? (
          <>
            <Alert severity="error">{gatewayError}</Alert>
            <Button variant="contained" onClick={() => void login()}>{t('sidebar.signin')}</Button>
          </>
        ) : (
          <>
            <CircularProgress />
            <Typography>{t('auth.linking_gateway')}</Typography>
          </>
        )}
      </Stack>
    </Box>
  );
}
