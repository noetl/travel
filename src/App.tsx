import { Box } from '@mui/material';
import { Route, Routes } from 'react-router-dom';
import { AuthCallback } from './auth/AuthCallback';
import { Sidebar } from './components/shell/Sidebar';
import { ChatThread } from './components/shell/ChatThread';
import { RightPane } from './components/shell/RightPane';

function Shell() {
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: '280px minmax(0, 1fr) 360px', minHeight: '100vh' }}>
      <Sidebar />
      <ChatThread />
      <RightPane />
    </Box>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/callback" element={<AuthCallback />} />
      <Route path="*" element={<Shell />} />
    </Routes>
  );
}
