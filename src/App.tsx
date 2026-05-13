import { Box } from '@mui/material';
import { Sidebar } from './components/shell/Sidebar';
import { ChatThread } from './components/shell/ChatThread';
import { RightPane } from './components/shell/RightPane';

export default function App() {
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: '280px minmax(0, 1fr) 360px', minHeight: '100vh' }}>
      <Sidebar />
      <ChatThread />
      <RightPane />
    </Box>
  );
}
