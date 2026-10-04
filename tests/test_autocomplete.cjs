const {test} = require('node:test');
const assert = require('node:assert/strict');
const {normalizeStopText, filterStops} = require('../public/autocomplete.js');
const catalog = ['ÜNİVERSİTE', 'UZUNÇİFTLİK', 'YENİ CUMA DOĞU'].map(name => ({name, key: normalizeStopText(name)}));

test('single-character input updates immediately and prioritizes prefix matches', () => {
  assert.deepEqual(filterStops(catalog, 'U').map(stop => stop.name), catalog.map(stop => stop.name));
  assert.deepEqual(filterStops(catalog, 'Uz').map(stop => stop.name), ['UZUNÇİFTLİK']);
  assert.deepEqual(filterStops(catalog, '').map(stop => stop.name), []);
});

test('Turkish accents, casing, whitespace and result limits', () => {
  assert.equal(normalizeStopText('  İĞÜŞÖÇ  ı '), 'igusoc i');
  assert.equal(filterStops(catalog, 'yeni cuma dogu')[0].name, 'YENİ CUMA DOĞU');
  assert.equal(filterStops(catalog, 'u', 1).length, 1);
  assert.deepEqual(filterStops(catalog, 'zzzz'), []);
});
