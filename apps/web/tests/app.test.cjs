const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../app.js'), 'utf8').split("els.refresh.addEventListener")[0];
function app(fetch) {
  const context = vm.createContext({ fetch, AbortController, setTimeout, clearTimeout, console, document: { getElementById: () => ({}) } });
  vm.runInContext(source, context);
  return context;
}
const response = value => ({ ok: true, json: async () => value });
test('simultaneous reads coalesce; refresh invalidates cached data', async () => {
  let calls = 0;
  const c = app(async () => response(++calls));
  const values = await Promise.all([c.api('/api/v1/projects/p/brief'), c.api('/api/v1/projects/p/brief')]);
  assert.deepEqual(values, [1, 1]);
  assert.equal(await c.api('/api/v1/projects/p/brief'), 1);
  c.clearReadCache();
  assert.equal(await c.api('/api/v1/projects/p/brief'), 2);
});
test('a response started before refresh cannot repopulate the cache', async () => {
  const resolve = [];
  const c = app(() => new Promise(r => resolve.push(r)));
  const old = c.api('/api/v1/projects');
  c.clearReadCache();
  const fresh = c.api('/api/v1/projects');
  resolve[1](response('new'));
  await fresh;
  resolve[0](response('old'));
  await old;
  assert.equal(await c.api('/api/v1/projects'), 'new');
});
test('failed reads are retryable, not cached', async () => {
  let calls = 0;
  const c = app(async () => ++calls === 1 ? { ok: false, status: 503 } : response('ready'));
  await assert.rejects(c.api('/api/v1/projects'), /503/);
  assert.equal(await c.api('/api/v1/projects'), 'ready');
});
test('one failed project section preserves other data', async () => {
  const c = app(async path => path.endsWith('/tasks') ? { ok: false, status: 503 } : response({ available: true }));
  const detail = await c.loadProject('p');
  assert.equal(detail.brief.available, true);
  assert.deepEqual(Array.from(detail.errors), ['tasks']);
});
test('historical weeks never masquerade as this week or last week', () => {
  const c = app(async () => response({}));
  assert.equal(c.weekLabel('2020-01-06', 0), '1月6日 – 1月12日');
  assert.match(c.weekLabel(c.dateKey(c.weekStart(new Date())), 9), /^本周/);
});
test('daily focus surfaces failures first and preserves stale evidence labels', () => {
  const c = app(async () => response({}));
  const items = c.dailyFocusItems([
    { project: { project_id: 'p1' }, brief: { issues: ['Needs review'], source_status: { freshness_reference_date: '2020-01-01' } } },
    { project: { project_id: 'p2' }, briefError: true },
  ]);
  assert.equal(items[0].kind, '来源异常');
  assert.equal(items[1].text, 'Needs review');
  assert.equal(items.filter(item => item.kind === '资料待更新').length, 2);
});
