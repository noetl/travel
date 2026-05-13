import { Box, Button, Paper, TextField, Typography } from '@mui/material';
import { useTranslation } from 'react-i18next';
import sampleEnvelopes from '../../contracts/sampleEnvelopes.json';
import { WidgetRenderer } from '../WidgetRenderer';

export function ChatThread() {
  const { t } = useTranslation();
  return (
    <Box sx={{ display: 'grid', gridTemplateRows: 'auto 1fr auto', minWidth: 0 }}>
      <Box sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider', bgcolor: 'background.paper' }}>
        <Typography variant="h6">Muno trip planner</Typography>
      </Box>
      <Box sx={{ overflow: 'auto', p: 2, display: 'grid', gap: 1.5, alignContent: 'start' }}>
        {sampleEnvelopes.slice(0, 6).map((envelope, index) => (
          <WidgetRenderer key={`${envelope.widget_type}-${index}`} envelope={envelope} />
        ))}
      </Box>
      <Paper component="form" sx={{ display: 'flex', gap: 1, p: 2, borderRadius: 0 }} onSubmit={(event) => event.preventDefault()}>
        <TextField fullWidth size="small" placeholder={t('chat.placeholder')} />
        <Button variant="contained" type="submit">{t('chat.send')}</Button>
      </Paper>
    </Box>
  );
}
