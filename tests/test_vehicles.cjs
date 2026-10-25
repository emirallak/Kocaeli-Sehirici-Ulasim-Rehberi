const {test} = require('node:test');
const assert = require('node:assert/strict');
const {vehicleSummary} = require('../public/vehicles.js');

test('vehicle popups describe the approach, next stop and simulated speed', () => {
  const lines = vehicleSummary({route_code: '100', headsign: 'Otogar', minutes_to_board: 6,
    next_stop: 'Merkez', minutes_to_next_stop: 2, speed_kmh: 15});
  assert.deepEqual(lines, ['100 · Otogar', 'Biniş durağına ~6 dk', 'Sonraki durak: Merkez · ~2 dk',
    'Simülasyon · ortalama 15 km/sa']);
  assert.equal(vehicleSummary({route_code: '7', minutes_to_board: 0, speed_kmh: 25})[1], 'Biniş durağına geliyor');
  assert.equal(vehicleSummary({route_code: '7', minutes_to_board: null, speed_kmh: 25}).length, 2);
  assert.equal(vehicleSummary({route_code: '7', passed_board: true, speed_kmh: 25})[1], 'Biniş durağını geçti');
  assert.equal(vehicleSummary({route_code: '7', target: 'Durağa', minutes_to_board: 3, remaining_stops: 2, speed_kmh: 25})[1],
    'Durağa ~3 dk · 2 durak');
});
