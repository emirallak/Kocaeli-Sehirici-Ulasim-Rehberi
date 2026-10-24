const {test} = require('node:test');
const assert = require('node:assert/strict');
const {fetchJSON} = require('../public/net.js');

const reply = (status, body) => ({ok: status < 400, status, json: async () => body});

test('a cold-start 503 or network failure is retried until it succeeds', async () => {
  const answers = [() => { throw new TypeError('network'); }, () => reply(503, {detail: 'warming'}), () => reply(200, {ok: 1})];
  global.fetch = async () => answers.shift()();
  const retries = [];
  const payload = await fetchJSON('/api/stops', {}, {retries: 2, onRetry: attempt => retries.push(attempt)});
  assert.deepEqual(payload, {ok: 1});
  assert.deepEqual(retries, [1, 2]);
});

test('validation errors are not retried and keep the API message', async () => {
  let calls = 0;
  global.fetch = async () => { calls++; return reply(422, {detail: {message: 'Durak bulunamadı: X.'}}); };
  await assert.rejects(fetchJSON('/api/chat', {}, {retries: 3}), {message: 'Durak bulunamadı: X.', status: 422});
  assert.equal(calls, 1);
});

test('a stalled request times out and reports a connection error', async () => {
  global.fetch = (url, {signal}) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(new Error('aborted'))));
  await assert.rejects(fetchJSON('/api/chat', {}, {timeout: 20, retries: 0}), {status: 0});
});
