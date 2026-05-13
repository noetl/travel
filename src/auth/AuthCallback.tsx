import { Alert, Box, CircularProgress, Typography } from '@mui/material';
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMunoAuth } from './MunoAuthProvider';

export function AuthCallback() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { isAuthConfigured, isLoading, isAuthenticated } = useMunoAuth();

  useEffect(() => {
    if (!isLoading && isAuthenticated) navigate('/', { replace: true });
  }, [isAuthenticated, isLoading, navigate]);

  if (!isAuthConfigured) {
    return (
      <Box sx={{ p: 4 }}>
        <Alert severity="warning">{t('auth.not_configured')}</Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
      <Box sx={{ textAlign: 'center' }}>
        <CircularProgress sx={{ mb: 2 }} />
        <Typography>{t('auth.loading')}</Typography>
      </Box>
    </Box>
  );
}
