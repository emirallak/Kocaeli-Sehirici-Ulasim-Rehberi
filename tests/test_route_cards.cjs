const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {document: {getElementById: () => ({addEventListener() {}})}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(require.resolve('../public/app.js'), 'utf8'), context);

test('one route step renders every interchangeable line in summary and details', () => {
  const leg = {route_code: '115', mode: 'Otobüs', board_stop: {name: 'Umuttepe'},
    alight_stop: {name: 'Çarşı'}, estimated_duration_minutes: 15,
    line_options: ['115', '115Ç', '33'].map(route_code => ({route_code, mode: 'Otobüs'}))};
  const html = context.routeCard({legs: [leg], estimated_duration_minutes: 20}, 0);
  for (const code of ['115', '115Ç', '33']) {
    assert.equal(html.split(` ${code}</span>`).length - 1, 2);
  }
  assert.ok(html.includes('Doğrudan · aktarmasız'));
  assert.equal((html.match(/class="journey-card/g) || []).length, 1);
});

test('legacy single-line payloads still work and option labels are escaped', () => {
  assert.ok(context.lineBadges({route_code: '100', mode: 'Otobüs'}).includes(' 100</span>'));
  const html = context.lineBadges({line_options: [{route_code: '<script>', mode: 'Otobüs'}]});
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(!html.includes('<script>'));
});

test('simulated upcoming vehicles appear in the card and specs cover every line option', () => {
  const leg = {route_code: '100', mode: 'Otobüs', board_stop: {name: 'Umuttepe'}, alight_stop: {name: 'Çarşı'},
    estimated_duration_minutes: 15, pattern_id: 1, board_index: 2, alight_index: 6,
    upcoming_arrivals: [{route_code: '100', at: '2026-03-02T08:34:00+03:00', minutes: 4}],
    line_options: [{route_code: '100', mode: 'Otobüs', patterns: [{pattern_id: 1, board_index: 2, alight_index: 6}]},
      {route_code: '<b>', mode: 'Otobüs', patterns: [{pattern_id: 7, board_index: 0, alight_index: 3}]}]};
  const html = context.routeCard({legs: [leg], estimated_duration_minutes: 20}, 0);
  assert.ok(html.includes('İlk araç'));
  assert.ok(html.includes('Sıradaki araçlar: 100 08:34 (4 dk)'));
  assert.equal(context.vehicleSpecs({legs: [{is_walking: true}, leg]}), '1:2:6,7:0:3');
  // Legacy payloads without upcoming arrivals render no simulation row.
  assert.ok(!context.routeCard({legs: [{...leg, upcoming_arrivals: undefined}]}, 0).includes('İlk araç'));
});
