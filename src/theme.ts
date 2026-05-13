import { alpha, createTheme } from '@mui/material/styles';

const adionaBlue = '#2F6DF6';
const deepNavy = '#13233A';
const paper = '#FFFFFF';
const softPanel = '#F5F7FB';

export const theme = createTheme({
  palette: {
    mode: 'light',
    primary: {
      main: adionaBlue,
      dark: '#2357D7',
      light: '#7EA6FF',
      contrastText: '#FFFFFF'
    },
    secondary: {
      main: '#00A88B',
      dark: '#087766',
      light: '#74DCCB',
      contrastText: '#FFFFFF'
    },
    background: {
      default: softPanel,
      paper
    },
    text: {
      primary: deepNavy,
      secondary: '#667085'
    },
    divider: alpha(deepNavy, 0.1),
    success: { main: '#1D9A6C' },
    warning: { main: '#F59E0B' },
    error: { main: '#D64545' },
    info: { main: '#2563EB' }
  },
  shape: { borderRadius: 10 },
  typography: {
    fontFamily: '"Inter", "Roboto", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    h5: { fontWeight: 700, letterSpacing: 0 },
    h6: { fontWeight: 700, letterSpacing: 0 },
    subtitle1: { fontWeight: 600, letterSpacing: 0 },
    subtitle2: { fontWeight: 600, letterSpacing: 0 },
    button: { fontWeight: 600, letterSpacing: 0, textTransform: 'none' }
  },
  shadows: [
    'none',
    '0 1px 2px rgba(19,35,58,0.06)',
    '0 4px 12px rgba(19,35,58,0.08)',
    '0 8px 24px rgba(19,35,58,0.10)',
    '0 12px 32px rgba(19,35,58,0.12)',
    '0 16px 40px rgba(19,35,58,0.14)',
    '0 18px 48px rgba(19,35,58,0.16)',
    '0 20px 56px rgba(19,35,58,0.18)',
    '0 22px 64px rgba(19,35,58,0.20)',
    '0 24px 72px rgba(19,35,58,0.22)',
    '0 26px 80px rgba(19,35,58,0.24)',
    '0 28px 88px rgba(19,35,58,0.26)',
    '0 30px 96px rgba(19,35,58,0.28)',
    '0 32px 104px rgba(19,35,58,0.30)',
    '0 34px 112px rgba(19,35,58,0.32)',
    '0 36px 120px rgba(19,35,58,0.34)',
    '0 38px 128px rgba(19,35,58,0.36)',
    '0 40px 136px rgba(19,35,58,0.38)',
    '0 42px 144px rgba(19,35,58,0.40)',
    '0 44px 152px rgba(19,35,58,0.42)',
    '0 46px 160px rgba(19,35,58,0.44)',
    '0 48px 168px rgba(19,35,58,0.46)',
    '0 50px 176px rgba(19,35,58,0.48)',
    '0 52px 184px rgba(19,35,58,0.50)',
    '0 54px 192px rgba(19,35,58,0.52)'
  ]
});
