import { Box, Divider, List, ListItemButton, ListItemText, Typography } from '@mui/material';
import { useTranslation } from 'react-i18next';

export function Sidebar() {
  const { t } = useTranslation();
  return (
    <Box sx={{ borderRight: '1px solid', borderColor: 'divider', bgcolor: 'background.paper', p: 2 }}>
      <Typography variant="h5" sx={{ mb: 2 }}>{t('app_name')}</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>{t('sidebar.guest')}</Typography>
      <Divider />
      <List dense>
        <ListItemButton><ListItemText primary={t('sidebar.searches')} /></ListItemButton>
        <ListItemButton><ListItemText primary={t('sidebar.orders')} /></ListItemButton>
      </List>
    </Box>
  );
}
