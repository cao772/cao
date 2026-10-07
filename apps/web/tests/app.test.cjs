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
test('daily focus coalesces old facts without representing them as current problems', () => {
  const c = app(async () => response({}));
  const items = c.dailyFocusItems([
    { project: { project_id: 'p1' }, brief: { issues: ['Needs review', 'Old issue'], next_steps: ['Old next step'], source_status: { freshness_reference_date: '2020-01-01' } } },
    { project: { project_id: 'p2' }, briefError: true },
  ]);
  assert.equal(items[0].kind, '来源异常');
  assert.equal(items.filter(item => item.kind === '历史事项待核对').length, 1);
  assert.match(items.find(item => item.kind === '历史事项待核对').text, /3 条/);
  assert.equal(items.filter(item => item.kind === '待核对问题').length, 0);
  assert.equal(items.filter(item => item.kind === '资料待更新').length, 1);
});
test('each fact keeps its own date even when another source is recent', () => {
  const c = app(async () => response({}));
  const today = new Date().toISOString().slice(0, 10);
  const items = c.dailyFocusItems([{ project: { project_id: 'p' }, brief: {
    issues: ['old issue', 'new issue', 'undated issue'],
    issue_evidence: [{text:'old issue',source_date:'2020-01-01'}, {text:'new issue',source_date:today}, {text:'undated issue',source_date:null}],
    source_status: {freshness_reference_date:today},
  }}]);
  assert.equal(items.filter(item => item.kind === '待核对问题').length, 2);
  assert.equal(items.find(item => item.text === 'undated issue').sourceDate, null);
  assert.equal(items.find(item => item.kind === '历史事项待核对').sourceDate, '2020-01-01');
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
  vm.runInContext("globalThis.realRenderProgress = renderProgress; globalThis.escapeHtml = value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('\"','&quot;');",c);
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


test('project progress keeps recorded and inferred stages distinct and exposes known issues', () => {
  const {c,elements}=intelligence(async()=>({}));
  c.realRenderProgress({context:{available:true,project:{current_stage:'代码同步完成，待验证'},current_work:['核对分支'],known_issues:['框架版本不兼容'],modified_at:'2026-09-24'},progress:{current_stage:'测试与验证',issues:[],source_status:{freshness_reference_date:'2026-09-01'}}});
  const html=elements.get('intelligence-progress').innerHTML;
  assert.match(html,/记录中的当前阶段/);
  assert.match(html,/代码同步完成，待验证/);
  assert.match(html,/材料自动汇总推断为“测试与验证”/);
  assert.match(html,/框架版本不兼容/);
  assert.match(html,/核对分支/);
  assert.doesNotMatch(html,/当前没有来自项目资料的待处理问题/);
});
test('progress does not use unavailable context or silently hide long lists', () => {
  const {c,elements}=intelligence(async()=>({}));
  c.realRenderProgress({context:{available:false,project:{current_stage:'忽略'},known_issues:['忽略']},progress:{current_stage:'资料阶段',completed:Array.from({length:8},(_,i)=>`成果${i}`)}});
  const html=elements.get('intelligence-progress').innerHTML;
  assert.doesNotMatch(html,/忽略/);
  assert.match(html,/资料推断阶段/);
  assert.match(html,/展开其余 2 项/);
  assert.match(html,/成果7/);
});
test('progress items escape source content and remove duplicate list markers', () => {
  const {c}=intelligence(async()=>({}));
  const html=c.progressItems(['- <script>unsafe</script>'],'');
  assert.match(html,/&lt;script&gt;/);
  assert.doesNotMatch(html,/<script>|<li>- /);
});

test('opening industry news during initial project load keeps that view open', async () => {
  let finishHealth;
  const c=app(path=>path==='/health' ? new Promise(resolve=>finishHealth=resolve) : Promise.resolve(response([{project_id:'p'}])));
  let newsActive=false;
  c.document.getElementById=()=>({classList:{contains:()=>newsActive}});
  vm.runInContext("renderProjectList = () => {}; showPortfolio = () => { throw new Error('unexpected navigation'); };",c);
  const loading=c.bootstrap();
  newsActive=true;
  finishHealth(response({status:'ok'}));
  assert.equal(await loading,true);
});
test('local material sources do not inflate linked code repository counts', () => {
  const c = app(async () => response({}));
  const rows = c.registeredCodeRepositories([
    { role: 'materials', url: 'file:///local/materials' },
    { role: 'application', url: 'file:///local/docs' },
    { role: 'application', url: 'https://github.com/example/project.git' },
  ]);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].url, 'https://github.com/example/project.git');
});


test('new historical evidence reopens a handled review even with the same source date', async () => {
  const c = app(async () => response({}));
  const row = issues => ({project:{project_id:'p'},brief:{issues,source_status:{freshness_reference_date:'2020-01-01'}}});
  const old = c.dailyFocusItems([row(['old issue'])])[0];
  const fresh = c.dailyFocusItems([row(['different issue'])])[0];
  assert.notEqual(await c.focusIdentity(old), await c.focusIdentity(fresh));
  const reordered = c.dailyFocusItems([row(['second','first'])])[0];
  const stable = c.dailyFocusItems([row(['first','second'])])[0];
  assert.equal(await c.focusIdentity(reordered), await c.focusIdentity(stable));
});
test('portfolio filtering searches identifiers, owners and exact groups without guessing categories', () => {
  const c = app(async () => response({}));
  const row = {project:{project_id:'stereo-distance',project_name:'Vision'},intelligence:{profile:{team:'研究原型',owner:'alice'}}};
  assert.equal(c.portfolioMatches(row,'stereo','team:研究原型'),true);
  assert.equal(c.portfolioMatches(row,'alice','team:研究原型'),true);
  assert.equal(c.portfolioMatches(row,'','team:业务项目'),false);
  assert.equal(c.portfolioMatches(row,'','__ungrouped__'),false);
  assert.equal(c.portfolioMatches({project:{project_id:'p'}},'','__ungrouped__'),true);
});


test('overview and copied brief use explicit stage records without promoting heuristic inference', () => {
  const c = app(async () => response({}));
  const stage = c.briefStage({current_stage:'测试与验证',recorded_stage:{stage:'业务阶段待核实',modified_at:'2026-10-01'}});
  assert.equal(stage.value,'业务阶段待核实');
  assert.equal(stage.label,'记录中的阶段');
  assert.match(stage.note,/需结合实际工作核对/);
  assert.equal(c.briefStage({current_stage:'测试与验证'}).label,'资料推断阶段');
});


test('global search labels filename-only hits without claiming original content was read', () => {
  const c=app(async () => response({}));
  vm.runInContext('els.globalSearchResults.querySelectorAll = () => []',c);
  c.renderGlobalSearchResults({query:'report',count:1,results:[{project_name:'Project',source_name:'report.md',source_path:'inventory-source-01/report.md',source_type:'material',metadata_only:true,snippet:'仅登记文件名'}]});
  const html=vm.runInContext('els.globalSearchResults.innerHTML',c);
  assert.match(html,/目录登记（未读取正文）/);
  assert.match(html,/inventory-source-01\/report.md/);
});


test('project load pool limits concurrency and preserves input order', async () => {
  const c=app(async () => response({}));let active=0,peak=0;
  const releases=[];
  const run=c.mapConcurrent([0,1,2,3,4,5],async n=>{active++;peak=Math.max(peak,active);await new Promise(r=>releases.push(r));active--;return n;},2);
  for(let i=0;i<6;i++){while(!releases[i]) await new Promise(r=>setImmediate(r));releases[i]();}
  assert.deepEqual(Array.from(await run),[0,1,2,3,4,5]);assert.equal(peak,2);
});
test('retry reads only failed sections and preserves successful project data', async () => {
  const calls=[];const c=app(async path=>{calls.push(path);return response({recovered:true});});
  vm.runInContext("renderPortfolio = () => {}; state.portfolioRows=[{project:{project_id:'p'},brief:{keep:true},briefError:false,intelligence:null,intelligenceError:true}]",c);
  await c.retryPortfolioRow('p');
  assert.deepEqual(calls,['/api/v1/projects/p/intelligence']);
  assert.equal(vm.runInContext('state.portfolioRows[0].brief.keep',c),true);
  assert.equal(vm.runInContext('state.portfolioRows[0].intelligenceError',c),false);
  assert.equal(vm.runInContext('state.retryingProjects.size',c),0);
});
test('duplicate retries coalesce and late results cannot overwrite a new portfolio load', async () => {
  let finish;let calls=0;const c=app(()=>{calls++;return new Promise(r=>finish=r);});
  vm.runInContext("renderPortfolio=()=>{}; state.portfolioRows=[{project:{project_id:'p'},briefError:true}]",c);
  const old=c.retryPortfolioRow('p');await c.retryPortfolioRow('p');assert.equal(calls,1);
  vm.runInContext("state.portfolioLoadId++;state.retryingProjects.clear();state.portfolioRows=[{project:{project_id:'p'},brief:{fresh:true}}]",c);
  finish(response({obsolete:true}));await old;
  assert.equal(vm.runInContext('state.portfolioRows[0].brief.fresh',c),true);
});

test('failed project cards expose recovery and prevent repeated clicks while retrying', () => {
  const c=app(async () => response({}));
  vm.runInContext("renderDailyFocus=()=>{};els.portfolioSearch.value='';els.portfolioGrid.querySelectorAll=()=>[];state.projects=[{project_id:'p'}];state.portfolioRows=[{project:state.projects[0],briefError:true,intelligenceError:false}];",c);
  c.renderPortfolio();
  assert.match(vm.runInContext('els.portfolioGrid.innerHTML',c),/data-portfolio-retry="p"/);
  assert.match(vm.runInContext('els.portfolioGrid.innerHTML',c),/重试未读部分/);
  vm.runInContext("state.retryingProjects.add('p')",c);c.renderPortfolio();
  assert.match(vm.runInContext('els.portfolioGrid.innerHTML',c),/data-portfolio-retry="p" disabled/);
});

test('facts expand without losing source dates and escape material paths', () => {
  const c = app(async () => response({}));
  const html = c.memoryTags(['one','two','three'], false, 1, [{text:'one',path:'docs/<plan>.md',source_date:'2026-09-01'}]);
  assert.match(html, /展开其余 2 项/);
  assert.match(html, /three/);
  assert.match(html, /资料日期 2026-09-01/);
  assert.match(html, /docs\/&lt;plan&gt;.md/);
  assert.match(html, /资料日期未知/);
  for (const path of ['/tmp/x','../x','docs/../x','file:x','https://x','docs\\x']) assert.equal(c.materialSourceQuery(path), null);
});
test('source navigation ignores a project change while loading', async () => {
  const c = app(async () => response({}));
  let resolve, searched = false;
  c.showIntelligenceView = () => new Promise(r => resolve = r);
  c.runIntelligenceSearch = () => { searched = true; };
  vm.runInContext("state.selectedProjectId='old'; state.projectLoadId=1",c);
  const pending = c.openFactSource('docs/plan.md');
  vm.runInContext("state.selectedProjectId='new'; state.projectLoadId=2",c);
  resolve(); await pending;
  assert.equal(searched,false);
});

test('dossier excludes generated inventory pages from evidence candidates', () => {
  const {c} = intelligence(async()=>({}));
  const facts=c.dossierFacts({materials:[
    {path:'inventory/catalog-001.md',modified_at:'2026-10-07',facts:[{text:'Generated index summary'}]},
    {path:'docs/report.md',modified_at:'2026-09-01',facts:[{text:'Original report evidence'}]},
  ]});
  assert.deepEqual(Array.from(facts,item=>item.text),['Original report evidence']);
  assert.equal(c.changeLabel('recently_modified'),'资料修改日期');
});


test('dossier next step cannot borrow freshness from unrelated records', () => {
  const {c}=intelligence(async()=>({}));
  const next=c.dossierNextStep({next_steps:['计划核对接口'], source_status:{freshness_reference_date:'2026-10-07'},
    next_step_evidence:[{text:'另一事项',path:'recent.md',source_date:'2026-10-07'}]});
  assert.equal(next.text,'计划核对接口');
  assert.equal(next.sourceDate,null);
  assert.equal(next.path,'尚未关联原始材料');
  const old=c.dossierNextStep({next_steps:['计划核对接口'], next_step_evidence:[{text:'计划核对接口',path:'old.md',source_date:'2026-08-01'}]});
  assert.equal(old.sourceDate,'2026-08-01');
  assert.equal(old.path,'old.md');
  assert.equal(c.dossierNextStep({}).text,'尚未识别明确下一步');
});
