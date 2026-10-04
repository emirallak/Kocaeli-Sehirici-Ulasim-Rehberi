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
