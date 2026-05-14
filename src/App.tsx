import { Alert, Box, Button, CircularProgress, Stack, Typography } from '@mui/material';
import { useState } from 'react';
import { Route, Routes } from 'react-router-dom';
import { AuthCallback } from './auth/AuthCallback';
import { useMunoAuth } from './auth/MunoAuthProvider';
import { Sidebar, type SidebarView } from './components/shell/Sidebar';
import { ChatThread } from './components/shell/ChatThread';
import { RightPane } from './components/shell/RightPane';

function Shell() {
  const [activeView, setActiveView] = useState<SidebarView>('searches');
  const [slotState, setSlotState] = useState<Record<string, unknown>>({});
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: '280px minmax(0, 1fr) 360px', minHeight: '100vh' }}>
      <Sidebar activeView={activeView} onViewChange={setActiveView} />
      <ChatThread activeView={activeView} onSlotStateChange={setSlotState} />
      <RightPane slotState={slotState} />
    </Box>
  );
}

function SignInPane() {
  const auth = useMunoAuth();
  const disabled = !auth.isAuthConfigured || auth.isLoading || auth.isLinkingGateway;
  const message = auth.gatewayError === 'session_expired' ? 'Your gateway session expired. Sign in again to continue.' : auth.gatewayError;

  return (
    <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center', bgcolor: 'background.default', p: 3 }}>
      <Stack spacing={2.5} sx={{ width: '100%', maxWidth: 420, bgcolor: 'background.paper', p: 4, borderRadius: 3, boxShadow: 3 }}>
        <Box>
          <Typography variant="h4" fontWeight={800}>Muno</Typography>
          <Typography variant="body1" color="text.secondary">
            Sign in to start planning.
          </Typography>
        </Box>
        {!auth.isAuthConfigured ? <Alert severity="warning">Auth0 is not configured for this build.</Alert> : null}
        {message ? <Alert severity="error">{message}</Alert> : null}
        {auth.isLinkingGateway ? (
          <Stack direction="row" spacing={1.5} alignItems="center">
            <CircularProgress size={20} />
            <Typography variant="body2">Linking to gateway...</Typography>
          </Stack>
        ) : null}
        <Button variant="contained" size="large" disabled={disabled} onClick={() => void auth.login()}>
          Sign in to start planning
        </Button>
      </Stack>
    </Box>
  );
}

function AuthenticatedShell() {
  const auth = useMunoAuth();
  if (auth.isLoading || auth.isLinkingGateway) {
    return <SignInPane />;
  }
  if (!auth.canUseApp) {
    return <SignInPane />;
  }
  return <Shell />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/callback" element={<AuthCallback />} />
      <Route path="*" element={<AuthenticatedShell />} />
    </Routes>
  );
}
