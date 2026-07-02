import { APIProvider, Map, AdvancedMarker, InfoWindow } from '@vis.gl/react-google-maps';
import { Box, Stack, Typography } from '@mui/material';
import { useEffect, useState } from 'react';
import type { MapViewPayload, HotelCardPayload } from '../../contracts/widgets';
import { WidgetCard, asPayload, withMapsKey, type WidgetComponentProps } from './widgetUtils';
import { HotelCard } from './HotelCard';

// Build a Static Maps URL for the same center/zoom/markers. The Static Maps
// API is a separate Google API from the interactive Maps JavaScript API and
// is already proven to load from the SPA (same key, `withMapsKey` appends it
// at request time). Used as the graceful fallback when the JS API fails to
// authenticate so the user never sees Google's raw "didn't load correctly"
// banner.
export function buildStaticMapUrl(data: MapViewPayload): string {
  const u = new URL('https://maps.googleapis.com/maps/api/staticmap');
  u.searchParams.set('center', `${data.center.lat},${data.center.lng}`);
  u.searchParams.set('zoom', String(data.zoom ?? 12));
  u.searchParams.set('size', '640x400');
  u.searchParams.set('scale', '2');
  (data.markers || []).slice(0, 20).forEach((marker) => {
    u.searchParams.append('markers', `color:0x1a73e8|${marker.lat},${marker.lng}`);
  });
  return withMapsKey(u.toString());
}

function StaticMapFallback({ data }: { data: MapViewPayload }) {
  const key = import.meta.env.VITE_GOOGLE_MAPS_KEY as string | undefined;
  const [imgFailed, setImgFailed] = useState(false);
  const showImage = Boolean(key) && !imgFailed;
  return (
    <WidgetCard>
      <Stack spacing={1}>
        {showImage ? (
          <Box sx={{ borderRadius: 2, overflow: 'hidden', boxShadow: 1 }}>
            <img
              src={buildStaticMapUrl(data)}
              alt="Trip map (static view)"
              style={{ width: '100%', display: 'block' }}
              onError={() => setImgFailed(true)}
            />
          </Box>
        ) : (
          <Box sx={{ height: 260, borderRadius: 2, bgcolor: 'primary.light', display: 'grid', placeItems: 'center', color: 'white', fontWeight: 700 }}>
            {data.center.lat.toFixed(3)}, {data.center.lng.toFixed(3)}
          </Box>
        )}
        <Typography variant="caption" color="text.secondary">
          Interactive map unavailable — showing static view.
        </Typography>
      </Stack>
    </WidgetCard>
  );
}

export function MapView({ payload }: WidgetComponentProps) {
  const data = asPayload<MapViewPayload>(payload);
  const [selected, setSelected] = useState(data.selected_marker_id || data.markers.find((marker) => marker.state === 'selected')?.hotel_id || '');
  const [authFailed, setAuthFailed] = useState(false);
  const selectedMarker = data.markers.find((marker) => marker.hotel_id === selected) || data.markers.find((marker) => marker.state === 'selected');
  const key = import.meta.env.VITE_GOOGLE_MAPS_KEY as string | undefined;

  // Google calls the global `window.gm_authFailure` when the Maps JavaScript
  // API loads but fails its auth check (ApiTargetBlockedMapError,
  // RefererNotAllowedMapError, BillingNotEnabledMapError, ApiNotActivatedMapError,
  // Invalid/Missing/ExpiredKey). Instead of letting @vis.gl render Google's raw
  // error banner, swap to the static-map fallback. Chain any pre-existing hook.
  useEffect(() => {
    const w = window as unknown as { gm_authFailure?: () => void };
    const prev = w.gm_authFailure;
    w.gm_authFailure = () => {
      setAuthFailed(true);
      if (typeof prev === 'function') {
        try { prev(); } catch { /* ignore */ }
      }
    };
    return () => { w.gm_authFailure = prev; };
  }, []);

  const syntheticHotel = (marker: MapViewPayload['markers'][number]): HotelCardPayload => ({
    hotel_id: marker.hotel_id || marker.label,
    name: marker.label,
    location: { lat: marker.lat, lng: marker.lng },
    score: 8.6,
    photos: [],
    amenities: [],
    currency: 'USD',
    price_per_night: 240,
    ctas: ['show_numbers']
  });

  if (!key || authFailed) {
    return <StaticMapFallback data={data} />;
  }
  return (
    <Box sx={{ height: 420, borderRadius: 2, overflow: 'hidden', position: 'relative', boxShadow: 2 }}>
      <APIProvider apiKey={key} onError={() => setAuthFailed(true)}>
        <Map defaultCenter={data.center} defaultZoom={data.zoom} mapId="muno-travel-map" gestureHandling="greedy" disableDefaultUI>
          {data.markers.map((marker) => (
            <AdvancedMarker key={marker.hotel_id || marker.label} position={{ lat: marker.lat, lng: marker.lng }} onClick={() => setSelected(marker.hotel_id || marker.label)}>
              <HotelCard payload={syntheticHotel(marker)} variantId="map_marker" />
            </AdvancedMarker>
          ))}
          {selectedMarker ? (
            <InfoWindow position={{ lat: selectedMarker.lat, lng: selectedMarker.lng }} onCloseClick={() => setSelected('')}>
              <Box sx={{ width: 240 }}>
                <HotelCard payload={syntheticHotel(selectedMarker)} variantId="in_popover" />
              </Box>
            </InfoWindow>
          ) : null}
        </Map>
      </APIProvider>
    </Box>
  );
}
