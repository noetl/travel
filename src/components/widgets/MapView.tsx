import { APIProvider, Map, AdvancedMarker, InfoWindow } from '@vis.gl/react-google-maps';
import { Box, Stack, Typography } from '@mui/material';
import { useState } from 'react';
import type { MapViewPayload, HotelCardPayload } from '../../contracts/widgets';
import { WidgetCard, asPayload, type WidgetComponentProps } from './widgetUtils';
import { HotelCard } from './HotelCard';

export function MapView({ payload }: WidgetComponentProps) {
  const data = asPayload<MapViewPayload>(payload);
  const [selected, setSelected] = useState(data.selected_marker_id || data.markers.find((marker) => marker.state === 'selected')?.hotel_id || '');
  const selectedMarker = data.markers.find((marker) => marker.hotel_id === selected) || data.markers.find((marker) => marker.state === 'selected');
  const key = import.meta.env.VITE_GOOGLE_MAPS_KEY as string | undefined;
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
  if (!key) {
    return (
      <WidgetCard>
        <Stack spacing={1}>
          <Typography variant="subtitle1">Map preview</Typography>
          <Typography variant="body2" color="text.secondary">Set VITE_GOOGLE_MAPS_KEY at build time to enable the live map.</Typography>
          <Box sx={{ height: 260, borderRadius: 2, bgcolor: 'primary.light', display: 'grid', placeItems: 'center', color: 'white', fontWeight: 700 }}>
            {data.center.lat.toFixed(3)}, {data.center.lng.toFixed(3)}
          </Box>
        </Stack>
      </WidgetCard>
    );
  }
  return (
    <Box sx={{ height: 420, borderRadius: 2, overflow: 'hidden', position: 'relative', boxShadow: 2 }}>
      <APIProvider apiKey={key}>
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
