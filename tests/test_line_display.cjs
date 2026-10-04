const {test} = require('node:test');
const assert = require('node:assert/strict');
const display = require('../public/line-display.js');

test('GTFS departures wrap the clock and retain their service-day offset', () => {
  for (const [raw, label, dayOffset] of [
    ['23:59:00', '23:59', 0], ['24:00', '00:00', 1],
    ['25:00:00', '01:00', 1], ['26:15:00', '02:15', 1],
    ['26:00:00', '02:00', 1], ['48:05:09', '00:05:09', 2],
    ['8:04:00', '08:04', 0],
  ]) assert.deepEqual(display.departure(raw), {label, dayOffset});
  for (const raw of ['', null, '24:70:00', '-1:00', 'hello']) {
    assert.equal(display.departure(raw).label, '—');
  }
});

test('restriction badges reflect explicit API prohibitions independently', () => {
  assert.deepEqual(display.restrictions({pickup_allowed: false, dropoff_allowed: true}), ['Binilmez']);
  assert.deepEqual(display.restrictions({pickup_allowed: true, dropoff_allowed: false}), ['İnilmez']);
  assert.deepEqual(display.restrictions({pickup_allowed: false, dropoff_allowed: false}), ['Binilmez', 'İnilmez']);
  assert.deepEqual(display.restrictions({pickup_allowed: true, dropoff_allowed: true}), []);
  assert.deepEqual(display.restrictions({}), []);
});
