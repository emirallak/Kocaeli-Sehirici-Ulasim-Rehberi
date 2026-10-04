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

test('condition colors are distinct and provide at least 4.5:1 text contrast', () => {
  const luminance = css => {
    const [h, sPercent, lPercent] = css.match(/[\d.]+/g).map(Number);
    const s = sPercent / 100, l = lPercent / 100;
    const a = s * Math.min(l, 1 - l);
    const rgb = [0, 8, 4].map(n => {
      const k = (n + h / 30) % 12;
      const channel = l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
      return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4;
    });
    return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
  };
  const colors = new Set();
  for (let index = 0; index < 100; index++) {
    const style = display.conditionStyle(index);
    assert.equal(style.number, index + 1);
    assert.ok((luminance(style.background) + .05) / (luminance(style.foreground) + .05) >= 4.5);
    assert.ok(!colors.has(style.background));
    colors.add(style.background);
  }
});
