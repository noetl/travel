import AddIcon from '@mui/icons-material/Add';
import CheckIcon from '@mui/icons-material/Check';
import FlightTakeoffIcon from '@mui/icons-material/FlightTakeoff';
import HotelIcon from '@mui/icons-material/Hotel';
import ImageIcon from '@mui/icons-material/Image';
import RemoveIcon from '@mui/icons-material/Remove';
import {
  Avatar,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  IconButton,
  Stack,
  Typography,
  alpha,
  Skeleton,
  useTheme
} from '@mui/material';
import { useState, type ReactNode } from 'react';

export interface WidgetEvent {
  type: 'widget_submit' | 'widget_cta_click';
  action_id?: string;
  value?: unknown;
}

export interface WidgetComponentProps<TPayload = unknown> {
  payload: TPayload;
  variantId?: string;
  onWidgetEvent?: (event: WidgetEvent) => void;
}

export function asPayload<TPayload>(payload: unknown): TPayload {
  return payload as TPayload;
}

export function emitWidgetEvent(
  onWidgetEvent: WidgetComponentProps['onWidgetEvent'] | undefined,
  event: WidgetEvent
) {
  onWidgetEvent?.(event);
}

export function money(value?: string | number, currency?: string) {
  if (value === undefined || value === null || value === '') return 'Price pending';
  const amount = typeof value === 'number' ? value.toFixed(0) : value;
  return currency ? `${currency} ${amount}` : String(amount);
}

export function compactTime(value?: string) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function compactDate(value?: string) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

export function WidgetCard({
  children,
  dense = false,
  highlighted = false,
  sx
}: {
  children: ReactNode;
  dense?: boolean;
  highlighted?: boolean;
  sx?: Record<string, unknown>;
}) {
  const theme = useTheme();
  return (
    <Card
      elevation={highlighted ? 3 : 1}
      sx={{
        borderRadius: 2,
        border: `1px solid ${highlighted ? theme.palette.primary.main : alpha(theme.palette.text.primary, 0.08)}`,
        overflow: 'hidden',
        ...sx
      }}
    >
      <CardContent sx={{ p: dense ? 1.5 : 2.25, '&:last-child': { pb: dense ? 1.5 : 2.25 } }}>
        {children}
      </CardContent>
    </Card>
  );
}

export function AgentAvatar({ label = 'A' }: { label?: string }) {
  return (
    <Avatar sx={{ width: 34, height: 34, bgcolor: 'primary.main', color: 'primary.contrastText', fontWeight: 700 }}>
      {label.slice(0, 1).toUpperCase()}
    </Avatar>
  );
}

export function EmptyPhoto({ icon = 'hotel' }: { icon?: 'hotel' | 'flight' | 'image' }) {
  const Icon = icon === 'flight' ? FlightTakeoffIcon : icon === 'hotel' ? HotelIcon : ImageIcon;
  return (
    <Box
      sx={{
        position: 'relative',
        bgcolor: 'background.default',
        color: 'text.secondary',
        minHeight: 120,
        display: 'grid',
        placeItems: 'center',
        overflow: 'hidden'
      }}
    >
      <Skeleton variant="rectangular" animation={false} sx={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }} />
      <Stack spacing={0.5} alignItems="center" sx={{ position: 'relative', zIndex: 1 }}>
        <Icon fontSize="large" />
        <Typography variant="caption">No photo available</Typography>
      </Stack>
    </Box>
  );
}

// Google Places/Static-Maps photo URLs arrive keyless from the server (the
// `google-maps-widget-key` secret is deliberately not embedded — a keyed URL
// would be scrubbed to "[REDACTED]" and fail the place_card `uri` contract).
// The browser supplies its own restricted VITE_GOOGLE_MAPS_KEY at <img> time so
// the image actually loads. Non-Google hosts (e.g. HotelBeds) pass through.
const GOOGLE_PHOTO_HOSTS = ['maps.googleapis.com', 'places.googleapis.com'];

export function withMapsKey(url: string): string {
  if (!url) return url;
  const key = import.meta.env.VITE_GOOGLE_MAPS_KEY as string | undefined;
  if (!key) return url;
  try {
    const parsed = new URL(url);
    if (!GOOGLE_PHOTO_HOSTS.includes(parsed.hostname) || parsed.searchParams.has('key')) return url;
    parsed.searchParams.set('key', key);
    return parsed.toString();
  } catch {
    return url;
  }
}

export function PhotoStrip({ photos, icon = 'hotel' }: { photos?: string[]; icon?: 'hotel' | 'flight' | 'image' }) {
  const [failed, setFailed] = useState(false);
  const rawFirst = photos?.find(Boolean);
  if (!rawFirst || failed) return <EmptyPhoto icon={icon} />;
  const first = withMapsKey(rawFirst);
  return (
    <Box
      sx={{
        minHeight: 150,
        bgcolor: 'background.default',
        position: 'relative',
        overflow: 'hidden'
      }}
    >
      <Box
        component="img"
        src={first}
        alt=""
        loading="lazy"
        onError={() => setFailed(true)}
        sx={{
          display: 'block',
          width: '100%',
          height: 150,
          objectFit: 'cover'
        }}
      />
      {photos && photos.length > 1 ? (
        <Chip
          size="small"
          label={`View all ${photos.length} photos`}
          sx={{ position: 'absolute', right: 8, bottom: 8, bgcolor: 'rgba(255,255,255,0.9)' }}
        />
      ) : null}
    </Box>
  );
}

export function StepperButton({
  direction,
  onClick
}: {
  direction: 'up' | 'down';
  onClick: () => void;
}) {
  return (
    <IconButton size="small" onClick={onClick} aria-label={direction === 'up' ? 'increase' : 'decrease'}>
      {direction === 'up' ? <AddIcon fontSize="small" /> : <RemoveIcon fontSize="small" />}
    </IconButton>
  );
}

export function ActionButton({
  label,
  actionId,
  onWidgetEvent,
  variant = 'outlined',
  value
}: {
  label: string;
  actionId: string;
  onWidgetEvent?: WidgetComponentProps['onWidgetEvent'];
  variant?: 'text' | 'outlined' | 'contained';
  value?: unknown;
}) {
  return (
    <Button
      size="small"
      variant={variant}
      startIcon={variant === 'contained' ? <CheckIcon /> : undefined}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        emitWidgetEvent(onWidgetEvent, { type: 'widget_cta_click', action_id: actionId, value });
      }}
    >
      {label}
    </Button>
  );
}

export function LabelValue({ label, value }: { label: string; value?: ReactNode }) {
  return (
    <Stack spacing={0.25}>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body2" fontWeight={600}>
        {value || '-'}
      </Typography>
    </Stack>
  );
}
