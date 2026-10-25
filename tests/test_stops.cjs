const {test} = require('node:test');
const assert = require('node:assert/strict');
const {arrivalParts, nearbyVehicles} = require('../public/stops.js');

test('arrival rows show minutes with remaining stops or the first-stop departure', () => {
  assert.deepEqual(arrivalParts({minutes: 4, remaining_stops: 3, at: '2026-03-02T08:34:00+03:00'}),
    {when: '4 dk', detail: '3 durak uzakta · 08:34'});
  assert.deepEqual(arrivalParts({minutes: 0, remaining_stops: 1, at: '2026-03-02T08:30:00+03:00'}).when, 'Geliyor');
  assert.equal(arrivalParts({minutes: 25, remaining_stops: null, departs_at: '2026-03-02T08:40:00+03:00',
    at: '2026-03-02T08:55:00+03:00'}).detail, 'İlk duraktan 08:40 kalkış · 08:55');
});

test('each nearby vehicle is drawn once, at its soonest arrival', () => {
  const vehicle = {id: 'v1', latitude: 40.7, longitude: 29.9, speed_kmh: 28};
  const vehicles = nearbyVehicles([
    {route_code: '100', mode: 'Otobüs', destination: 'Merkez', minutes: 3, remaining_stops: 2, vehicle},
    {route_code: '100', mode: 'Otobüs', destination: 'Merkez', minutes: 9, remaining_stops: 7, vehicle},
    {route_code: '7', mode: 'Otobüs', destination: 'Otogar', minutes: 20, remaining_stops: null, vehicle: null},
  ]);
  assert.equal(vehicles.length, 1);
  assert.equal(vehicles[0].minutes_to_board, 3);
  assert.equal(vehicles[0].headsign, 'Merkez');
});
