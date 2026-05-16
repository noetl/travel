import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import FlightIcon from '@mui/icons-material/Flight';
import HotelIcon from '@mui/icons-material/Hotel';
import PlaceIcon from '@mui/icons-material/Place';
import ConfirmationNumberIcon from '@mui/icons-material/ConfirmationNumber';
import EventNoteIcon from '@mui/icons-material/EventNote';
import {
  Avatar,
  Box,
  Button,
  Collapse,
  Divider,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Stack,
  Typography
} from '@mui/material';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useMunoAuth, type MunoUser } from '../../auth/MunoAuthProvider';

export type SidebarView = 'searches' | 'orders';

export interface ChatHistoryItem {
  id: string;
  label: string;
  subtitle?: string;
  widgetType: string;
}

export interface ChatHistorySummary {
  searches: ChatHistoryItem[];
  orders: ChatHistoryItem[];
  threadId?: string;
}

const WIDGET_ICONS: Record<string, ReactNode> = {
  flight_list: <FlightIcon fontSize="small" />,
  flight_card: <FlightIcon fontSize="small" />,
  hotel_list: <HotelIcon fontSize="small" />,
  hotel_card: <HotelIcon fontSize="small" />,
  place_list: <PlaceIcon fontSize="small" />,
  place_card: <PlaceIcon fontSize="small" />,
  order_confirmation: <ConfirmationNumberIcon fontSize="small" />,
  itinerary_summary: <EventNoteIcon fontSize="small" />,
  calendar_view: <EventNoteIcon fontSize="small" />
};

export function SidebarAccount({
  isAuthConfigured,
  isAuthenticated,
  isLoading,
  user,
  onLogin,
  onLogout
}: {
  isAuthConfigured: boolean;
  isAuthenticated: boolean;
  isLoading: boolean;
  user?: MunoUser;
  onLogin: () => void;
  onLogout: () => void;
}) {
  const { t } = useTranslation();
  if (isLoading) {
    return <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>{t('auth.loading')}</Typography>;
  }

  if (isAuthenticated) {
    return (
      <Stack spacing={1.25} sx={{ mb: 2 }}>
        <Stack direction="row" spacing={1} alignItems="center">
          <Avatar src={user?.picture} alt={user?.name || user?.email || 'User'} sx={{ width: 34, height: 34 }}>
            {(user?.name || user?.email || 'U').slice(0, 1).toUpperCase()}
          </Avatar>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="body2" fontWeight={700} noWrap>
              {user?.name || user?.email || t('sidebar.signed_in')}
            </Typography>
            <Typography variant="caption" color="text.secondary" noWrap>
              {user?.email || user?.sub}
            </Typography>
          </Box>
        </Stack>
        <Button size="small" variant="outlined" onClick={onLogout}>{t('sidebar.signout')}</Button>
      </Stack>
    );
  }

  return (
    <Stack spacing={1} sx={{ mb: 2 }}>
      <Typography variant="body2" color="text.secondary">
        {isAuthConfigured ? t('sidebar.guest') : t('sidebar.auth_unconfigured')}
      </Typography>
      <Button size="small" variant="contained" onClick={onLogin} disabled={!isAuthConfigured}>
        {t('sidebar.signin')}
      </Button>
    </Stack>
  );
}

function HistorySection({
  view,
  label,
  items,
  activeView,
  onActivate,
  onSelectItem,
  defaultOpen
}: {
  view: SidebarView;
  label: string;
  items: ChatHistoryItem[];
  activeView: SidebarView;
  onActivate: (view: SidebarView) => void;
  onSelectItem: (item: ChatHistoryItem) => void;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen ?? true);
  const selected = activeView === view;
  return (
    <>
      <ListItemButton
        selected={selected}
        onClick={() => {
          onActivate(view);
          setOpen((prev) => !prev);
        }}
      >
        <ListItemText
          primary={label}
          secondary={items.length ? `${items.length} item${items.length === 1 ? '' : 's'}` : 'No items yet'}
          secondaryTypographyProps={{ variant: 'caption' }}
        />
        {open ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
      </ListItemButton>
      <Collapse in={open} unmountOnExit>
        <List dense disablePadding>
          {items.length === 0 ? (
            <Box sx={{ pl: 4, pr: 2, py: 0.5 }}>
              <Typography variant="caption" color="text.disabled">
                {view === 'orders'
                  ? 'No orders yet. Book a flight to add one.'
                  : 'No searches yet. Ask Muno to plan a trip.'}
              </Typography>
            </Box>
          ) : (
            items.map((item) => (
              <ListItemButton
                key={item.id}
                sx={{ pl: 4 }}
                onClick={() => {
                  onActivate(view);
                  onSelectItem(item);
                }}
              >
                <ListItemIcon sx={{ minWidth: 28 }}>
                  {WIDGET_ICONS[item.widgetType] ?? <EventNoteIcon fontSize="small" />}
                </ListItemIcon>
                <ListItemText
                  primary={item.label}
                  secondary={item.subtitle || undefined}
                  primaryTypographyProps={{ variant: 'body2', noWrap: true }}
                  secondaryTypographyProps={{ variant: 'caption', noWrap: true }}
                />
              </ListItemButton>
            ))
          )}
        </List>
      </Collapse>
    </>
  );
}

export function Sidebar({
  activeView,
  onViewChange,
  summary,
  onSelectHistoryItem
}: {
  activeView: SidebarView;
  onViewChange: (view: SidebarView) => void;
  summary?: ChatHistorySummary;
  onSelectHistoryItem?: (item: ChatHistoryItem) => void;
}) {
  const { t } = useTranslation();
  const auth = useMunoAuth();
  const searches = summary?.searches ?? [];
  const orders = summary?.orders ?? [];
  return (
    <Box sx={{ borderRight: '1px solid', borderColor: 'divider', bgcolor: 'background.paper', p: 2, overflow: 'auto' }}>
      <Typography variant="h5" sx={{ mb: 2 }}>{t('app_name')}</Typography>
      <SidebarAccount
        isAuthConfigured={auth.isAuthConfigured}
        isAuthenticated={auth.isAuthenticated}
        isLoading={auth.isLoading}
        user={auth.user}
        onLogin={() => void auth.login()}
        onLogout={auth.logout}
      />
      <Divider />
      <List dense>
        <HistorySection
          view="searches"
          label={t('sidebar.searches')}
          items={searches}
          activeView={activeView}
          onActivate={onViewChange}
          onSelectItem={(item) => onSelectHistoryItem?.(item)}
          defaultOpen
        />
        <HistorySection
          view="orders"
          label={t('sidebar.orders')}
          items={orders}
          activeView={activeView}
          onActivate={onViewChange}
          onSelectItem={(item) => onSelectHistoryItem?.(item)}
          defaultOpen
        />
      </List>
    </Box>
  );
}
