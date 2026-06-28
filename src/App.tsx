import { Alert, Box, Button, CircularProgress, Drawer, Stack, Typography, useMediaQuery } from '@mui/material';
import { useTheme } from '@mui/material/styles';
import { useCallback, useState } from 'react';
import { Route, Routes } from 'react-router-dom';
import { AuthCallback } from './auth/AuthCallback';
import { useMunoAuth } from './auth/MunoAuthProvider';
import { Sidebar, type ChatHistorySummary, type SidebarView } from './components/shell/Sidebar';
import { ChatThread } from './components/shell/ChatThread';
import { RightPane } from './components/shell/RightPane';

function mergeSlotState(
  current: Record<string, unknown>,
  next: Record<string, unknown>
): Record<string, unknown> {
  return {
    ...current,
    ...next,
    region: next.region || current.region,
    party: next.party || current.party
  };
}

function Shell() {
  const theme = useTheme();
  // Below `md` (900px) the three fixed columns can't fit a phone viewport, so
  // reflow to a single column (chat) with the side panels as temporary drawers.
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));
  const [activeView, setActiveView] = useState<SidebarView>('searches');
  const [slotState, setSlotState] = useState<Record<string, unknown>>({});
  const [summary, setSummary] = useState<ChatHistorySummary>({ searches: [], orders: [] });
  const [scrollToMessageId, setScrollToMessageId] = useState<string | undefined>();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [tripStateOpen, setTripStateOpen] = useState(false);

  const handleSlotChange = useCallback((next: Record<string, unknown>) => {
    setSlotState((current) => mergeSlotState(current, next));
  }, []);

  const sidebar = (
    <Sidebar
      activeView={activeView}
      onViewChange={setActiveView}
      summary={summary}
      onSelectHistoryItem={(item) => {
        setScrollToMessageId(item.id);
        if (isMobile) setSidebarOpen(false);
      }}
    />
  );

  const chat = (
    <ChatThread
      activeView={activeView}
      onSlotStateChange={handleSlotChange}
      onSummaryChange={setSummary}
      scrollToMessageId={scrollToMessageId}
      onScrollHandled={() => setScrollToMessageId(undefined)}
      onViewChange={setActiveView}
      onOpenSidebar={isMobile ? () => setSidebarOpen(true) : undefined}
      onOpenTripState={isMobile ? () => setTripStateOpen(true) : undefined}
    />
  );

  const rightPane = <RightPane slotState={slotState} />;

  if (isMobile) {
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', height: '100dvh' }}>
        <Box sx={{ flex: 1, minHeight: 0, display: 'grid' }}>{chat}</Box>
        <Drawer
          anchor="left"
          open={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
          ModalProps={{ keepMounted: true }}
          PaperProps={{ sx: { width: 'min(300px, 85vw)' } }}
        >
          {sidebar}
        </Drawer>
        <Drawer
          anchor="right"
          open={tripStateOpen}
          onClose={() => setTripStateOpen(false)}
          ModalProps={{ keepMounted: true }}
          PaperProps={{ sx: { width: 'min(340px, 88vw)' } }}
        >
          {rightPane}
        </Drawer>
      </Box>
    );
  }

  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: '280px minmax(0, 1fr) 360px', minHeight: '100vh' }}>
      {sidebar}
      {chat}
      {rightPane}
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
