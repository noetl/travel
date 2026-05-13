import { Button, Paper, TextField } from '@mui/material';
import { useTranslation } from 'react-i18next';

export function InputBar() {
  const { t } = useTranslation();
  return (
    <Paper component="form" sx={{ display: 'flex', gap: 1, p: 2, borderRadius: 0 }} onSubmit={(event) => event.preventDefault()}>
      <TextField fullWidth size="small" placeholder={t('chat.placeholder')} />
      <Button variant="contained" type="submit">{t('chat.send')}</Button>
    </Paper>
  );
}
