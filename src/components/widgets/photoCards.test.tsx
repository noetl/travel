import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { HotelCard } from './HotelCard';
import { PlaceCard } from './PlaceCard';

describe('photo card rendering', () => {
  it('renders a place hero image when photos are present', () => {
    const html = renderToStaticMarkup(
      <PlaceCard
        payload={{
          place_id: 'place_1',
          name: 'Eiffel Tower',
          types: ['landmark'],
          photos: ['https://example.test/eiffel.jpg'],
          address: 'Paris'
        }}
      />
    );

    expect(html).toContain('src="https://example.test/eiffel.jpg"');
    expect(html).toContain('Eiffel Tower');
  });

  it('renders a themed placeholder when a place has no photos', () => {
    const html = renderToStaticMarkup(
      <PlaceCard payload={{ place_id: 'place_2', name: 'No Photo', types: ['city'], photos: [], address: 'Paris' }} />
    );

    expect(html).toContain('No photo available');
  });

  it('renders the first hotel photo and a count badge', () => {
    const html = renderToStaticMarkup(
      <HotelCard
        payload={{
          hotel_id: 'hotel_1',
          name: 'Central Stay',
          score: 8.7,
          photos: ['https://example.test/hotel-1.jpg', 'https://example.test/hotel-2.jpg'],
          amenities: ['wifi'],
          currency: 'USD',
          price_per_night: 180
        }}
      />
    );

    expect(html).toContain('src="https://example.test/hotel-1.jpg"');
    expect(html).toContain('View all 2 photos');
  });
});
