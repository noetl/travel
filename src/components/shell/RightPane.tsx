import { Box, Typography } from '@mui/material';
import { useTranslation } from 'react-i18next';
import sampleEnvelopes from '../../contracts/sampleEnvelopes.json';
import { WidgetRenderer } from '../WidgetRenderer';

export function RightPane() {
  const { t } = useTranslation();
  return (
    <Box sx={{ borderLeft: '1px solid', borderColor: 'divider', bgcolor: 'background.paper', p: 2, overflow: 'auto' }}>
      <Typography variant="h6" sx={{ mb: 2 }}>{t('right_pane.title')}</Typography>
      <WidgetRenderer envelope={sampleEnvelopes.find((item) => item.widget_type === 'property_block') ?? sampleEnvelopes[0]} />
    </Box>
  );
}
