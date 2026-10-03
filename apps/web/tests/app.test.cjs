const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../app.js'), 'utf8').split("els.refresh.addEventListener")[0];
function app(fetch, storage = new Map()) {
  const context = vm.createContext({ fetch, URLSearchParams, AbortController, setTimeout, clearTimeout, console, crypto: require('node:crypto').webcrypto, TextEncoder, localStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) }, document: { getElementById: () => ({}) } });
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

test('handling survives reload, stores no project text, and can be restored', async () => {
  const storage = new Map();
  const c = app(async () => response({}), storage);
  const item = { row: { project: { project_id: 'private-project' }, brief: { source_status: { freshness_reference_date: '2026-10-01' } } }, kind: '待核对问题', priority: 1, text: 'private material content' };
  const id = await c.focusIdentity(item);
  c.saveFocusTracking(id, 'done');
  const reloaded = app(async () => response({}), storage);
  assert.equal(reloaded.focusStatus(reloaded.readFocusTracking()[id]), 'done');
  assert.doesNotMatch([...storage.values()].join(''), /private-project|private material content/);
  reloaded.saveFocusTracking(id, 'restore');
  assert.equal(reloaded.focusStatus(reloaded.readFocusTracking()[id]), 'open');
});
test('new facts reappear, while daily age changes preserve a handled reminder', async () => {
  const c = app(async () => response({}));
  const item = { row: { project: { project_id: 'p' }, brief: { source_status: { freshness_reference_date: '2026-09-01' } } }, kind: '待核对问题', priority: 1, text: 'old fact' };
  assert.notEqual(await c.focusIdentity(item), await c.focusIdentity({ ...item, text: 'new fact' }));
  const stale = { ...item, priority: 3, kind: '资料待更新' };
  assert.equal(await c.focusIdentity(stale), await c.focusIdentity({ ...stale, text: 'one more day' }));
});
test('snooze expires exactly at the stored next-day boundary', () => {
  const c = app(async () => response({}));
  const id = 'a'.repeat(64);
  c.saveFocusTracking(id, 'snooze');
  const record = c.readFocusTracking()[id];
  const boundary = new Date(record.until);
  assert.equal(boundary.getHours(), 0);
  assert.equal(boundary.getMinutes(), 0);
  assert.equal(c.focusStatus(record, record.until - 1), 'snoozed');
  assert.equal(c.focusStatus(record, record.until), 'open');
});
test('damaged browser state is safely ignored and invalid actions are rejected', () => {
  const storage = new Map([['cao.focus.v1', '{broken']]);
  const c = app(async () => response({}), storage);
  assert.equal(Object.keys(c.readFocusTracking()).length, 0);
  assert.throws(() => c.saveFocusTracking('bad-id', 'done'), /invalid/);
});

test('search highlights literal matches without injecting source HTML or interpreting regex', () => {
  const c = app(async () => response({}));
  assert.equal(c.highlightEvidence('<script>TS-999</script>', 'TS-999'), '&lt;script&gt;<mark>TS-999</mark>&lt;/script&gt;');
  assert.equal(c.highlightEvidence('env_file a.b acb', 'a.b'), 'env_file <mark>a.b</mark> acb');
  assert.equal(c.highlightEvidence('缺陷处置', '缺陷'), '<mark>缺陷</mark>处置');
});
test('load more appends results and changing search scope restarts at zero', async () => {
  const offsets = [];
  const c = app(async path => {
    const offset = Number(new URL(path, 'http://localhost').searchParams.get('offset'));
    offsets.push(offset);
    return response({ offset, results: Array.from({length: 30}, (_, i) => ({project_id:'p', source_type:'material', source_id:offset + i})), count:70, has_more:true });
  });
  vm.runInContext("els.globalSearchInput.value='query'; els.globalSearchSource.value='all'; els.globalSearchProject.value=''; renderGlobalSearchResults = () => {};", c);
  c.document.getElementById = () => ({value:'recent'});
  await c.runGlobalSearch();
  await c.runGlobalSearch(true);
  assert.equal(vm.runInContext('state.searchPayload.results.length', c), 60);
  vm.runInContext("els.globalSearchProject.value='other'", c);
  await c.runGlobalSearch(true);
  assert.deepEqual(offsets, [0,30,0]);
});

function intelligence(api) {
  const elements = new Map();
  const c = vm.createContext({api, URLSearchParams, state: {selectedProjectId:'p', projects:[]}, projectLabel:()=> 'Project', document:{getElementById(id){
    if (!elements.has(id)) elements.set(id, {innerHTML:'old project', value:'query', checked:false, classList:{add(){},remove(){}}});
    return elements.get(id);
  }}});
  const code = fs.readFileSync(require('node:path').join(__dirname,'../project-intelligence.js'),'utf8').split("intelligenceEls.open?.addEventListener")[0];
  vm.runInContext(code,c);
  vm.runInContext("for (const name of ['renderDossier','renderIntelligenceSummary','renderProgress','renderRepositories','renderMaterialCategories','renderSeries','renderRecentChanges','renderHealth']) globalThis[name] = data => { globalThis.rendered = data; }; renderSearchResults = data => { globalThis.result = data; };", c);
  return {c, elements};
}
test('project intelligence clears previous content and ignores late same-project loads', async () => {
  const resolve = [];
  const {c,elements} = intelligence(() => new Promise(r=>resolve.push(r)));
  const old = c.loadProjectIntelligence('p');
  assert.doesNotMatch(elements.get('intelligence-progress').innerHTML,/old project/);
  const fresh = c.loadProjectIntelligence('p');
  resolve[1]({context:{available:true},summary:{},version:'new'});
  await fresh;
  resolve[0]({version:'old'});
  await old;
  assert.equal(c.rendered.version,'new');
});
test('late search responses cannot overwrite a newer query or release its button', async () => {
  const resolve=[];
  const {c,elements} = intelligence(()=>new Promise(r=>resolve.push(r)));
  vm.runInContext("intelligenceState.projectId='p'",c);
  const old=c.runIntelligenceSearch();
  elements.get('intelligence-search-input').value='new';
  const fresh=c.runIntelligenceSearch();
  resolve[0]({query:'old'}); await old;
  assert.equal(c.result,undefined);
  assert.equal(elements.get('intelligence-search-btn').disabled,true);
  resolve[1]({query:'new'}); await fresh;
  assert.equal(c.result.query,'new');
  assert.equal(elements.get('intelligence-search-btn').disabled,false);
});
test('leaving a project prevents an in-flight search from changing the page', async () => {
  let finish;
  const {c} = intelligence(()=>new Promise(r=>finish=r));
  vm.runInContext("intelligenceState.projectId='p'",c);
  const search=c.runIntelligenceSearch();
  c.state.selectedProjectId='other';
  finish({query:'private previous project'}); await search;
  assert.equal(c.result,undefined);
});
test('failed intelligence load clears loading placeholders and allows search retry', async () => {
  const {c,elements}=intelligence(async()=>{throw new Error('503');});
  await assert.rejects(c.loadProjectIntelligence('p'),/503/);
  assert.match(elements.get('intelligence-progress').innerHTML,/读取失败/);
  assert.equal(elements.get('intelligence-search-btn').disabled,false);
});
