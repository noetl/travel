import { useState } from 'react';
import ConfirmationNumberIcon from '@mui/icons-material/ConfirmationNumber';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import PictureAsPdfIcon from '@mui/icons-material/PictureAsPdf';
import { Box, Button, Chip, Collapse, Divider, Stack, Typography } from '@mui/material';
import type { OrderConfirmationPayload } from '../../contracts/widgets';
import { WidgetCard, asPayload, emitWidgetEvent, money, type WidgetComponentProps } from './widgetUtils';

interface Segment {
  origin?: { iata_code?: string; name?: string; iata_city_code?: string };
  destination?: { iata_code?: string; name?: string; iata_city_code?: string };
  departing_at?: string;
  arriving_at?: string;
  marketing_carrier?: { iata_code?: string; name?: string };
  marketing_carrier_flight_number?: string;
  duration?: string;
}

interface Slice {
  origin?: { iata_code?: string; name?: string };
  destination?: { iata_code?: string; name?: string };
  duration?: string;
  segments?: Segment[];
}

interface Passenger {
  given_name?: string;
  family_name?: string;
  name?: string;
  email?: string;
}

interface Document {
  unique_identifier?: string;
  type?: string;
  document_url?: string;
}

function formatTime(value?: string): string {
  if (!value) return '';
  const trimmed = value.includes('T') ? value.replace('T', ' ').slice(0, 16) : value;
  return trimmed;
}

function passengerLabel(p: Passenger, index: number): string {
  const given = p.given_name?.trim();
  const family = p.family_name?.trim();
  const composed = [given, family].filter(Boolean).join(' ').trim();
  return composed || String(p.name || `Passenger ${index + 1}`);
}

export function OrderConfirmation({ payload, onWidgetEvent }: WidgetComponentProps) {
  const data = asPayload<OrderConfirmationPayload & { documents?: Document[] }>(payload);
  const [expanded, setExpanded] = useState(false);

  const passengers = (data.passengers as Passenger[] | undefined) ?? [];
  const slices = (data.slices as Slice[] | undefined) ?? [];
  const documents = data.documents ?? [];
  const pdfDoc = documents.find((d) => (d.document_url || '').toLowerCase().includes('.pdf'))
    || documents.find((d) => Boolean(d.document_url));

  return (
    <WidgetCard highlighted>
      <Stack spacing={1.5}>
        <Stack direction="row" spacing={1.25} alignItems="center">
          <Box sx={{ width: 44, height: 44, display: 'grid', placeItems: 'center', borderRadius: 2, bgcolor: 'success.main', color: 'white' }}>
            <ConfirmationNumberIcon />
          </Box>
          <Stack>
            <Typography variant="h6">Booking confirmed</Typography>
            <Typography variant="body2" color="text.secondary">Reference {data.booking_reference}</Typography>
          </Stack>
        </Stack>
        <Typography variant="h5" color="primary">{money(data.total_amount, data.total_currency)}</Typography>
        <Stack direction="row" gap={0.75} flexWrap="wrap">
          {passengers.slice(0, 4).map((passenger, index) => (
            <Chip key={index} label={passengerLabel(passenger, index)} />
          ))}
        </Stack>
        <Divider />
        <Stack direction="row" spacing={1} flexWrap="wrap">
          {data.ctas?.includes('view_full') ? (
            <Button
              variant="outlined"
              startIcon={expanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
              onClick={() => setExpanded((current) => !current)}
            >
              {expanded ? 'Hide details' : 'View full order'}
            </Button>
          ) : null}
          {pdfDoc?.document_url ? (
            <Button
              variant="outlined"
              color="primary"
              startIcon={<PictureAsPdfIcon />}
              component="a"
              href={pdfDoc.document_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              Download PDF
            </Button>
          ) : null}
          {data.ctas?.includes('new_search') ? (
            <Button
              variant="contained"
              onClick={() => emitWidgetEvent(onWidgetEvent, { type: 'widget_cta_click', action_id: 'new_search' })}
            >
              New search
            </Button>
          ) : null}
        </Stack>
        <Collapse in={expanded} unmountOnExit>
          <Stack spacing={1.5} sx={{ pt: 1 }}>
            {slices.length ? (
              <Stack spacing={1.25}>
                <Typography variant="subtitle2">Itinerary</Typography>
                {slices.map((slice, sliceIndex) => (
                  <Box key={sliceIndex} sx={{ borderLeft: 2, borderColor: 'primary.main', pl: 1.25 }}>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      {slice.origin?.iata_code || '?'} → {slice.destination?.iata_code || '?'}
                      {slice.duration ? ` · ${slice.duration}` : ''}
                    </Typography>
                    {(slice.segments ?? []).map((seg, segIndex) => (
                      <Typography key={segIndex} variant="caption" component="div" color="text.secondary">
                        {seg.marketing_carrier?.iata_code || ''}{seg.marketing_carrier_flight_number || ''}
                        {' · '}
                        {seg.origin?.iata_code || '?'} {formatTime(seg.departing_at)}
                        {' → '}
                        {seg.destination?.iata_code || '?'} {formatTime(seg.arriving_at)}
                      </Typography>
                    ))}
                  </Box>
                ))}
              </Stack>
            ) : null}
            {passengers.length ? (
              <Stack spacing={0.5}>
                <Typography variant="subtitle2">Passengers</Typography>
                {passengers.map((p, index) => (
                  <Typography key={index} variant="body2" color="text.secondary">
                    {passengerLabel(p, index)}{p.email ? ` · ${p.email}` : ''}
                  </Typography>
                ))}
              </Stack>
            ) : null}
            {documents.length > 1 ? (
              <Stack spacing={0.5}>
                <Typography variant="subtitle2">All documents</Typography>
                {documents.map((doc, index) => (
                  doc.document_url ? (
                    <Typography key={doc.unique_identifier || index} variant="body2">
                      <a href={doc.document_url} target="_blank" rel="noopener noreferrer">
                        {doc.type || `Document ${index + 1}`}
                      </a>
                    </Typography>
                  ) : null
                ))}
              </Stack>
            ) : null}
          </Stack>
        </Collapse>
      </Stack>
    </WidgetCard>
  );
}
