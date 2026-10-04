const state = { projects: [], selectedProjectId: null, detail: null, portfolioRows: [], portfolioLoadId: 0, projectLoadId: 0, globalSearchLoadId: 0, searchPayload: null, searchKey: null, searchOffset: 0 };

const els = {
  projectList: document.getElementById('project-list'),
  title: document.getElementById('project-title'),
  subtitle: document.getElementById('project-subtitle'),
  overview: document.getElementById('overview'),
  taskTable: document.getElementById('task-table'),
  taskScope: document.getElementById('task-scope'),
  projectMemory: document.getElementById('project-memory'),
  contributors: document.getElementById('contributors'),
  timeline: document.getElementById('timeline'),
  timelineCount: document.getElementById('timeline-count'),
  refresh: document.getElementById('refresh-btn'),
  apiState: document.getElementById('api-state'),
  apiStateText: document.getElementById('api-state-text'),
  toast: document.getElementById('toast'),
  portfolioNav: document.getElementById('portfolio-nav'),
  portfolioView: document.getElementById('portfolio-view'),
  portfolioOverview: document.getElementById('portfolio-overview'),
  portfolioGrid: document.getElementById('portfolio-grid'),
  portfolioStatus: document.getElementById('portfolio-status'),
  portfolioSearch: document.getElementById('portfolio-search'),
  portfolioRefresh: document.getElementById('portfolio-refresh-btn'),
  globalSearchInput: document.getElementById('global-search-input'),
  globalSearchProject: document.getElementById('global-search-project'),
  globalSearchSource: document.getElementById('global-search-source'),
  globalSearchButton: document.getElementById('global-search-btn'),
  globalSearchStatus: document.getElementById('global-search-status'),
  globalSearchResults: document.getElementById('global-search-results'),
};

// Keep project reads in memory briefly; never persist private content in browser storage.
const readCache = new Map();
const pendingReads = new Map();
let readGeneration = 0;
function clearReadCache() {
  readGeneration += 1;
  readCache.clear();
  pendingReads.clear();
}
async function api(path) {
  const cacheable = path.startsWith('/api/v1/projects');
  const cached = readCache.get(path);
  if (cacheable && cached && Date.now() - cached.at < 30000) return cached.value;
  if (cacheable && pendingReads.has(path)) return pendingReads.get(path);
  const generation = readGeneration;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  const request = (async () => {
    try {
      const response = await fetch(path, { headers: { Accept: 'application/json' }, signal: controller.signal });
      if (!response.ok) throw new Error(`服务返回 ${response.status}，请稍后重试`);
      const value = await response.json();
      if (cacheable && generation === readGeneration) {
        if (readCache.size >= 80) readCache.delete(readCache.keys().next().value);
        readCache.set(path, { value, at: Date.now() });
      }
      return value;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('连接超过 15 秒，请检查服务后刷新');
      throw error;
    } finally {
      clearTimeout(timer);
      if (generation === readGeneration) pendingReads.delete(path);
    }
  })();
  if (cacheable) pendingReads.set(path, request);
  return request;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function statusTone(status) {
  const value = String(status || '');
  if (['completed', 'success', 'ok'].includes(value)) return 'good';
  if (value.includes('fail') || value === 'blocked' || value === 'attention' || value === 'deployment_failed') return 'bad';
  if (value.includes('pending') || value.includes('review') || value.includes('uncommitted') || value.includes('unpushed')) return 'warn';
  if (value === 'active' || value.includes('progress') || value.includes('detected')) return 'info';
  return 'neutral';
}

function showToast(message, error = false) {
  els.toast.textContent = message;
  els.toast.className = `toast show${error ? ' error' : ''}`;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { els.toast.className = 'toast'; }, 3200);
}

function projectLabel(project) {
  return project.project_name || project.project_id || '未命名项目';
}

function renderProjectList() {
  if (!state.projects.length) {
    els.projectList.innerHTML = '<div class="empty">暂无项目</div>';
    return;
  }
  els.projectList.innerHTML = state.projects.map(project => {
    const active = project.project_id === state.selectedProjectId ? ' active' : '';
    const stateLabel = project.project_state_label || '暂无明显进展';
    return `
      <button class="project-item${active}" data-project-id="${escapeHtml(project.project_id)}">
        <span class="name">${escapeHtml(projectLabel(project))}</span>
        <span class="meta"><span>${escapeHtml(stateLabel)}</span><span>${project.contributor_count || 0} 人</span></span>
      </button>`;
  }).join('');
  els.projectList.querySelectorAll('[data-project-id]').forEach(button => {
    button.addEventListener('click', () => selectProject(button.dataset.projectId));
  });
}

function portfolioDate(value) {
  if (!value) return '时间未知';
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
}

function portfolioSourceDate(row) {
  return row.brief?.source_status?.freshness_reference_date || row.intelligence?.context?.modified_at || null;
}

function portfolioAgeDays(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return Math.max(0, Math.floor((Date.now() - date.getTime()) / 86400000));
}

function portfolioStat(label, value, note, attention = false) {
  return `<div class="portfolio-stat${attention ? ' attention' : ''}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(note)}</small></div>`;
}

function dailyFocusItems(rows) {
  const items = [];
  for (const row of rows) {
    const date = portfolioSourceDate(row);
    const age = portfolioAgeDays(date);
    const textOf = value => typeof value === 'string' ? value : value?.text || value?.title || '';
    const issues = [...new Set((row.brief?.issues || []).map(textOf).filter(Boolean))];
    const nextSteps = [...new Set((row.brief?.next_steps || []).map(textOf).filter(Boolean))];
    if (row.briefError || row.intelligenceError) items.push({ row, priority: 0, kind: '来源异常', text: '部分项目资料读取失败，请打开项目核对或刷新重试。' });
    for (const issue of issues) items.push({ row, priority: 1, kind: '待核对问题', text: issue });
    for (const next of nextSteps) items.push({ row, priority: 2, kind: '可推进事项', text: next });
    if (age === null || age > 14) items.push({ row, priority: 3, kind: '资料待更新', text: age === null ? '资料日期未知，请核对当前背景与进展。' : `资料距今 ${age} 天，请核对上述事项是否仍然有效。` });
  }
  return items.sort((a, b) => a.priority - b.priority);
}
const focusStorageKey = 'cao.focus.v1';
let focusRenderVersion = 0;
function readFocusTracking() {
  try {
    const parsed = JSON.parse(localStorage.getItem(focusStorageKey) || '{}');
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    return Object.fromEntries(Object.entries(parsed).filter(([key, value]) =>
      /^[a-f0-9]{64}$/.test(key) && value && ['done', 'snoozed'].includes(value.status)
      && Number.isFinite(value.updatedAt) && (value.status !== 'snoozed' || Number.isFinite(value.until))));
  } catch { return {}; }
}
async function focusIdentity(item) {
  // Age in days changes daily; source date, not age, identifies a stale-source reminder.
  const identity = [item.row.project.project_id, item.kind, portfolioSourceDate(item.row), item.priority === 3 ? '' : item.text];
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(identity)));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
}
function focusStatus(record, now = Date.now()) {
  if (record?.status === 'done') return 'done';
  return record?.status === 'snoozed' && record.until > now ? 'snoozed' : 'open';
}
function saveFocusTracking(id, action) {
  if (!/^[a-f0-9]{64}$/.test(id) || !['done', 'snooze', 'restore'].includes(action)) throw new Error('invalid focus action');
  const records = readFocusTracking();
  if (action === 'restore') delete records[id];
  else {
    const tomorrow = new Date();
    tomorrow.setHours(24, 0, 0, 0);
    records[id] = { status: action === 'done' ? 'done' : 'snoozed', updatedAt: Date.now(), until: action === 'done' ? null : tomorrow.getTime() };
  }
  // Bound metadata growth; only fingerprints and handling state are persisted.
  const entries = Object.entries(records).sort((a, b) => b[1].updatedAt - a[1].updatedAt).slice(0, 1000);
  localStorage.setItem(focusStorageKey, JSON.stringify(Object.fromEntries(entries)));
}
async function renderDailyFocus(rows) {
  const version = ++focusRenderVersion;
  const target = document.getElementById('daily-focus-items');
  const records = readFocusTracking();
  let items;
  try {
    items = await Promise.all(dailyFocusItems(rows).map(async item => {
      const id = await focusIdentity(item);
      return { ...item, id, status: focusStatus(records[id]) };
    }));
  } catch {
    if (version === focusRenderVersion) target.innerHTML = '<p class="muted">当前浏览器无法生成跟进标识，请使用 localhost 或安全连接。下方项目目录仍可使用。</p>';
    return;
  }
  if (version !== focusRenderVersion) return;
  const includeHandled = document.getElementById('focus-show-handled').checked;
  const visible = items.filter(item => includeHandled || item.status === 'open');
  const expanded = document.getElementById('focus-show-all').checked;
  const displayed = expanded ? visible : visible.slice(0, 8);
  const openCount = items.filter(item => item.status === 'open').length;
  document.getElementById('focus-count').textContent = `待关注 ${openCount} · 已处理 ${items.filter(item => item.status === 'done').length} · 稍后 ${items.filter(item => item.status === 'snoozed').length}`;
  document.getElementById('daily-focus-date').textContent = new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' });
  target.innerHTML = visible.length ? displayed.map(item => `<article class="daily-focus-item">
    <div><span class="badge ${item.priority < 2 ? 'warn' : 'neutral'}">${escapeHtml(item.kind)}</span><strong>${escapeHtml(projectLabel(item.row.project))}</strong></div>
    <p>${escapeHtml(item.text)}</p>
    <small>资料日期：${escapeHtml(portfolioDate(portfolioSourceDate(item.row)))}</small>
    ${item.status !== 'open' ? `<small>${item.status === 'done' ? '已处理此提醒（不代表项目问题已解决）' : '明天重新提醒'}</small>` : ''}
    <div class="focus-actions"><button type="button" class="secondary-button" data-focus-project="${escapeHtml(item.row.project.project_id)}">查看依据与进展</button>
    ${item.status === 'open' ? `<button type="button" class="secondary-button" data-focus-id="${item.id}" data-focus-action="done">已处理</button><button type="button" class="secondary-button" data-focus-id="${item.id}" data-focus-action="snooze">明天再看</button>` : `<button type="button" class="secondary-button" data-focus-id="${item.id}" data-focus-action="restore">恢复关注</button>`}</div>
  </article>`).join('') : `<p class="muted">${items.length ? '当前提醒已处理或延后。勾选“显示已处理和稍后事项”可恢复关注。' : '已读取的资料中暂未发现待关注事项。可从下方项目目录继续查看。'}</p>`;
  if (displayed.length < visible.length) target.insertAdjacentHTML('beforeend', `<p class="muted">另有 ${visible.length - displayed.length} 项，勾选“展开全部事项”查看。</p>`);
  target.querySelectorAll('[data-focus-project]').forEach(button => button.addEventListener('click', () => selectProject(button.dataset.focusProject)));
  target.querySelectorAll('[data-focus-action]').forEach(button => button.addEventListener('click', () => {
    try {
      saveFocusTracking(button.dataset.focusId, button.dataset.focusAction);
      renderDailyFocus(state.portfolioRows);
      showToast('跟进状态已保存到当前浏览器');
    } catch { showToast('浏览器不允许保存，跟进状态未更改。请检查浏览器存储设置。', true); }
  }));
}

function renderPortfolio() {
  const rows = state.portfolioRows;
  renderDailyFocus(rows);
  const incomplete = rows.some(row => row.briefError || row.intelligenceError);
  const complete = rows.filter(row => !row.briefError && !row.intelligenceError).length;
  const materialRows = rows.filter(row => row.intelligence);
  const repoCount = materialRows.reduce((sum, row) => sum + (row.intelligence.profile?.repositories?.length || 0), 0);
  const materialCount = materialRows.reduce((sum, row) => sum + (row.intelligence.summary?.material_count || 0), 0);
  const attentionCount = state.projects.filter(project => project.project_state === 'attention').length;
  const oldSourceCount = rows.filter(row => (portfolioAgeDays(portfolioSourceDate(row)) ?? 0) > 14).length;
  const unknownSourceCount = rows.filter(row => !portfolioSourceDate(row)).length;
  els.portfolioOverview.innerHTML = [
    portfolioStat('业务项目', state.projects.length, '当前已接入'),
    portfolioStat('需要关注', attentionCount, '根据项目采集状态', attentionCount > 0),
    portfolioStat('已识别资料', materialRows.length ? materialCount : '—', `${materialRows.length}/${state.projects.length} 个项目可读取`),
    portfolioStat('关联仓库', materialRows.length ? repoCount : '—', `${materialRows.length}/${state.projects.length} 个项目可读取`),
  ].join('');
  const status = incomplete
    ? `已读取 ${complete}/${state.projects.length} 个项目的完整概况；部分来源暂不可用。`
    : `已读取 ${state.projects.length} 个项目的背景与最新概况。`;
  els.portfolioStatus.textContent = `${status}${oldSourceCount ? ` ${oldSourceCount} 个项目资料超过 14 天，建议核对。` : ''}${unknownSourceCount ? ` ${unknownSourceCount} 个项目资料时间未知。` : ''}`;

  const query = els.portfolioSearch.value.trim().toLocaleLowerCase();
  let filtered = rows.filter(row => {
    const brief = row.brief || {};
    const knowledge = row.intelligence || {};
    return [projectLabel(row.project), knowledge.profile?.description, knowledge.context?.project?.purpose,
      knowledge.context?.project?.current_stage, brief.current_stage, ...(brief.next_steps || [])]
      .some(value => String(value || '').toLocaleLowerCase().includes(query));
  });
  if (document.getElementById('portfolio-attention').checked) {
    filtered = filtered.filter(row => row.project.project_state === 'attention' || row.brief?.issues?.length || row.briefError || row.intelligenceError);
  }
  const sort = document.getElementById('portfolio-sort').value;
  filtered.sort((a, b) => sort === 'name'
    ? projectLabel(a.project).localeCompare(projectLabel(b.project), 'zh-CN')
    : sort === 'recent'
      ? (Date.parse(b.project.last_seen_at) || 0) - (Date.parse(a.project.last_seen_at) || 0)
      : (b.brief?.issues?.length || 0) - (a.brief?.issues?.length || 0));
  document.getElementById('portfolio-match-count').textContent = `显示 ${filtered.length} / ${rows.length} 个项目`;
  els.portfolioGrid.innerHTML = filtered.length ? filtered.map(row => {
    const project = row.project;
    const brief = row.brief || {};
    const knowledge = row.intelligence || {};
    const description = knowledge.profile?.description || knowledge.context?.project?.purpose || '背景资料尚未接入';
    const stage = knowledge.context?.project?.current_stage || brief.current_stage || '尚未识别';
    const nextRaw = (brief.next_steps || [])[0] || (knowledge.context?.project?.current_work || [])[0] || '尚未识别明确下一步';
    const next = String(nextRaw).replace(/^\s*[-*•]\s*/, '');
    const issueCount = brief.issues?.length;
    const materialCount = knowledge.summary?.material_count;
    const repositories = knowledge.profile?.repositories?.length;
    const groups = knowledge.communications?.group_count;
    const sourceDate = portfolioSourceDate(row);
    const sourceAge = portfolioAgeDays(sourceDate);
    const tone = project.project_state === 'attention' ? 'warn' : project.project_state === 'active' ? 'info' : 'neutral';
    return `<article class="portfolio-card">
      <div class="portfolio-card-head"><span class="portfolio-card-id">${escapeHtml(project.project_id)}</span><span class="badge ${tone}">${escapeHtml(project.project_state_label || '状态待确认')}</span></div>
      <h4>${escapeHtml(projectLabel(project))}</h4>
      <p class="portfolio-card-description">${escapeHtml(description)}</p>
      <div class="portfolio-focus"><span>当前阶段</span><strong>${escapeHtml(stage)}</strong></div>
      <div class="portfolio-focus next"><span>下一步</span><strong title="${escapeHtml(next)}">${escapeHtml(next)}</strong></div>
      <div class="portfolio-facts">
        <span class="${issueCount ? 'issue' : ''}">问题 ${issueCount ?? '—'}</span>
        <span>资料 ${materialCount ?? '—'}</span><span>仓库 ${repositories ?? '—'}</span><span>群聊 ${groups ?? '—'}</span>
      </div>
      <div class="portfolio-date${sourceAge === null || sourceAge > 14 ? ' stale' : ''}">资料日期：${escapeHtml(portfolioDate(sourceDate))}${sourceAge > 14 ? `（距今 ${sourceAge} 天，建议核对）` : ''} · 本地采集：${escapeHtml(portfolioDate(project.last_seen_at))}</div>
      ${row.briefError || row.intelligenceError ? '<p class="portfolio-error">部分概况读取失败，详情中可能有更多信息。</p>' : ''}
      <div class="portfolio-actions">
        <button class="portfolio-open" type="button" data-portfolio-open="${escapeHtml(project.project_id)}">查看进展</button>
        <button class="portfolio-knowledge" type="button" data-portfolio-knowledge="${escapeHtml(project.project_id)}">资料与沟通</button>
      </div>
    </article>`;
  }).join('') : `<div class="portfolio-empty">${rows.length ? '没有符合条件的项目。请清除关键词或取消待关注筛选。' : '暂无项目，等待首次采集。'}</div>`;
  els.portfolioGrid.querySelectorAll('[data-portfolio-open]').forEach(button => {
    button.addEventListener('click', () => selectProject(button.dataset.portfolioOpen));
  });
  els.portfolioGrid.querySelectorAll('[data-portfolio-knowledge]').forEach(button => {
    button.addEventListener('click', () => {
      selectProject(button.dataset.portfolioKnowledge);
      showIntelligenceView();
    });
  });
}

async function loadPortfolio() {
  const loadId = ++state.portfolioLoadId;
  els.portfolioStatus.textContent = '正在汇总项目背景、资料和进度…';
  if (!state.portfolioRows.length) els.portfolioGrid.innerHTML = '<div class="portfolio-empty">正在读取项目概况…</div>';
  const rows = await Promise.all(state.projects.map(async project => {
    const encoded = encodeURIComponent(project.project_id);
    const [brief, intelligence] = await Promise.allSettled([
      api(`/api/v1/projects/${encoded}/brief`),
      api(`/api/v1/projects/${encoded}/intelligence`),
    ]);
    return {
      project,
      brief: brief.status === 'fulfilled' ? brief.value : null,
      intelligence: intelligence.status === 'fulfilled' ? intelligence.value : null,
      briefError: brief.status === 'rejected',
      intelligenceError: intelligence.status === 'rejected',
    };
  }));
  if (loadId !== state.portfolioLoadId) return;
  state.portfolioRows = rows;
  renderPortfolio();
}

function showPortfolio() {
  document.getElementById('news-view')?.classList.add('hidden');
  document.getElementById('news-nav')?.classList.remove('active');
  state.selectedProjectId = null;
  renderProjectList();
  els.portfolioNav.classList.add('active');
  document.getElementById('settings-nav')?.classList.remove('active');
  document.getElementById('settings-view')?.classList.add('hidden');
  document.getElementById('intelligence-view')?.classList.add('hidden');
  document.getElementById('dashboard-view')?.classList.add('hidden');
  els.portfolioView.classList.remove('hidden');
  const selectedSearchProject = els.globalSearchProject.value;
  els.globalSearchProject.innerHTML = '<option value="">全部项目</option>' + state.projects.map(project => `<option value="${escapeHtml(project.project_id)}">${escapeHtml(project.project_name || project.project_id)}</option>`).join('');
  if (state.projects.some(project => project.project_id === selectedSearchProject)) els.globalSearchProject.value = selectedSearchProject;
  return loadPortfolio().catch(error => {
    els.portfolioStatus.textContent = '项目概况读取失败';
    els.portfolioGrid.innerHTML = '<div class="portfolio-empty">读取失败，请点击“刷新数据”重试。</div>';
    showToast(`读取项目总览失败：${error.message}`, true);
  });
}

function highlightEvidence(value, query) {
  const text = String(value || '');
  const terms = [...new Set(String(query || '').trim().split(/\s+/).filter(Boolean))].sort((a, b) => b.length - a.length);
  if (!terms.length) return escapeHtml(text);
  const expression = new RegExp(terms.map(term => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'gi');
  let html = '', cursor = 0;
  for (const match of text.matchAll(expression)) {
    html += escapeHtml(text.slice(cursor, match.index)) + `<mark>${escapeHtml(match[0])}</mark>`;
    cursor = match.index + match[0].length;
  }
  return html + escapeHtml(text.slice(cursor));
}

function renderGlobalSearchResults(payload) {
  const results = payload.results || [];
  const unavailable = payload.unavailable_projects || [];
  document.getElementById('global-search-more').hidden = !payload.has_more;
  els.globalSearchStatus.textContent = `候选范围内找到 ${payload.count || 0} 项${results.length < (payload.count || 0) ? `，显示前 ${results.length} 项` : ''}。${payload.conversation_available === false ? ' 授权沟通尚未接入此部署。' : ''}${unavailable.length ? ` ${unavailable.length} 个项目材料暂不可用。` : ''}${payload.truncated_sources?.length ? ' 部分来源超过候选上限，请限定项目或使用更具体关键词。' : ''} 每项目各来源最多 100 项，按${payload.order === 'recent' ? '来源时间' : '相关性'}排序。`;
  els.globalSearchResults.innerHTML = results.length ? results.map((item, index) => `
    <article class="portfolio-search-hit">
      <strong>${escapeHtml(item.project_name)} · ${highlightEvidence(item.source_name || '未命名来源', payload.query)}</strong>
      ${item.snippet ? `<p>${highlightEvidence(item.snippet, payload.query)}</p>` : ''}
      ${item.matched_fields?.length ? `<small>命中：${escapeHtml(item.matched_fields.join('、'))}${item.locator ? ` · 位置：${escapeHtml(typeof item.locator === 'object' ? JSON.stringify(item.locator) : item.locator)}` : ''}</small>` : ''}
      <small>${escapeHtml(item.source_type === 'conversation' ? '授权沟通' : '项目材料')} · ${escapeHtml(item.source_path || item.sender || '')} · 来源时间 ${escapeHtml(portfolioDate(item.source_time))} · 本机采集 ${escapeHtml(portfolioDate(item.observed_at))}</small>
      <button type="button" data-global-search-open="${index}">在项目中查看</button>
    </article>`).join('') : '<div class="portfolio-empty">没有找到匹配内容。试试项目名、文件名或更短的业务关键词。</div>';
  els.globalSearchResults.querySelectorAll('[data-global-search-open]').forEach(button => button.addEventListener('click', async () => {
    const item = results[Number(button.dataset.globalSearchOpen)];
    if (!item) return;
    const opening = selectProject(item.project_id);
    const requestId = state.projectLoadId;
    await opening;
    if (state.projectLoadId !== requestId || state.selectedProjectId !== item.project_id || document.getElementById('dashboard-view').classList.contains('hidden')) return;
    await showIntelligenceView();
    if (state.projectLoadId !== requestId || state.selectedProjectId !== item.project_id || document.getElementById('intelligence-view').classList.contains('hidden')) return;
    const searchInput = document.getElementById('intelligence-search-input');
    if (searchInput) searchInput.value = payload.query;
    await runIntelligenceSearch();
  }));
}

async function runGlobalSearch(loadMore = false) {
  const query = els.globalSearchInput.value.trim();
  if (!query) {
    els.globalSearchStatus.textContent = '请输入关键词。';
    return;
  }
  const order = document.getElementById('global-search-order').value;
  const searchKey = JSON.stringify([query, els.globalSearchSource.value, els.globalSearchProject.value, order]);
  const append = loadMore === true && state.searchKey === searchKey && state.searchPayload;
  const offset = append ? state.searchOffset : 0;
  const requestId = ++state.globalSearchLoadId;
  const moreButton = document.getElementById('global-search-more');
  moreButton.disabled = true;
  if (!append) moreButton.hidden = true;
  els.globalSearchButton.disabled = true;
  els.globalSearchStatus.textContent = '正在检索已采集的项目材料与授权沟通…';
  const params = new URLSearchParams({ q: query, source: els.globalSearchSource.value, limit: '30', offset: String(offset), order });
  if (els.globalSearchProject.value) params.set('project_id', els.globalSearchProject.value);
  try {
    const payload = await api(`/api/v1/search?${params}`);
    if (requestId === state.globalSearchLoadId) {
      state.searchOffset = payload.offset + payload.results.length;
      if (append) {
        const seen = new Set();
        payload.results = [...state.searchPayload.results, ...payload.results].filter(item => {
          const key = JSON.stringify([item.project_id, item.source_type, item.source_id]);
          if (seen.has(key)) return false;
          seen.add(key); return true;
        });
      }
      state.searchPayload = payload;
      state.searchKey = searchKey;
      renderGlobalSearchResults(payload);
    }
  } catch (error) {
    if (requestId === state.globalSearchLoadId) {
      els.globalSearchStatus.textContent = `检索失败：${error.message}`;
      if (!append) els.globalSearchResults.innerHTML = '';
      else moreButton.hidden = false;
    }
  } finally {
    if (requestId === state.globalSearchLoadId) { els.globalSearchButton.disabled = false; moreButton.disabled = false; }
  }
}

function metric(label, value, note = '', small = false) {
  return `
    <div class="metric-card">
      <div class="metric-label">${escapeHtml(label)}</div>
      <div class="metric-value${small ? ' small' : ''}">${escapeHtml(value)}</div>
      <div class="metric-note">${escapeHtml(note)}</div>
    </div>`;
}

function renderOverview(project, detail) {
  const brief = detail.brief || {};
  const summary = brief.summary || {};
  const contributors = detail.contributors || {};
  const rollup = detail.current?.project_rollup || {};
  const issueCount = (brief.issues || []).length;
  const contributorCount = contributors.contributor_count ?? rollup.contributor_count ?? project.contributor_count ?? 0;
  const localCount = contributors.local_contributor_count ?? rollup.local_contributor_count ?? 0;
  els.overview.innerHTML = [
    metric('当前阶段', brief.current_stage || '尚未识别', '以最新项目资料和近期开发活动为准', true),
    metric('参与人员', contributorCount, localCount ? `${localCount} 人已接入本地工作区` : '根据项目仓库活动识别'),
    metric('进行中任务', summary.in_progress_task_count ?? 0, `${summary.planned_task_count ?? 0} 项明确待办`),
    metric('待处理问题', issueCount, issueCount ? '需要继续跟进' : '当前未识别到明确问题'),
    metric('本周提交', summary.weekly_commit_count ?? 0, `${summary.weekly_merge_count ?? 0} 次代码合并`),
  ].join('');
}

function isVisibleCurrentTask(item) {
  const status = String(item.status || '');
  if (status === 'planned') return Boolean(item.task_id) || String(item.origin || '') === 'agent';
  if (status === 'completed') return false;
  return true;
}

function renderTasks(detail) {
  const tasks = detail.tasks || {};
  const allItems = tasks.work_items || [];
  const items = allItems.filter(isVisibleCurrentTask).slice(0, 12);
  const hiddenCandidates = allItems.filter(item => String(item.status || '') === 'planned' && !isVisibleCurrentTask(item)).length;
  els.taskScope.textContent = items.length ? `${items.length} 项当前事项` : '当前无明确任务';
  els.taskScope.className = `badge ${items.length ? 'info' : 'neutral'}`;
  if (!items.length) {
    const candidateNote = hiddenCandidates ? `另有 ${hiddenCandidates} 条历史或待确认候选，未作为当前任务展示。` : '';
    els.taskTable.innerHTML = `<div class="empty task-empty">当前未识别到正在执行的明确任务。${escapeHtml(candidateNote)}</div>`;
    return;
  }
  els.taskTable.innerHTML = `
    <table>
      <thead><tr><th>任务</th><th>当前状态</th><th>参与人员</th><th>进展说明</th></tr></thead>
      <tbody>
        ${items.map(item => {
          const contributors = (item.contributors || []).join('、') || '-';
          const reasons = (item.status_reasons || []).slice(0, 2);
          return `<tr>
            <td><div class="task-title">${escapeHtml(item.title || item.task_id || '未命名事项')}</div>${item.task_id ? `<div class="muted task-id">${escapeHtml(item.task_id)}</div>` : ''}</td>
            <td><span class="badge ${statusTone(item.status)}">${escapeHtml(item.status_label || item.status || '未知')}</span></td>
            <td>${escapeHtml(contributors)}</td>
            <td><div class="reason-list">${reasons.length ? reasons.map(escapeHtml).join('<br>') : '-'}</div></td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>
    ${hiddenCandidates ? `<div class="table-footnote">已收起 ${hiddenCandidates} 条仅来自历史资料或尚未确认的任务候选。</div>` : ''}`;
}

function memoryTags(items, blocker = false, limit = 6) {
  if (!items || !items.length) return '<span class="muted">暂无</span>';
  return `<div class="memory-tags">${items.slice(0, limit).map(item => {
    const text = typeof item === 'string' ? item : (item.text || item.title || item.content || JSON.stringify(item));
    return `<span class="memory-tag${blocker ? ' blocker' : ''}">${escapeHtml(text)}</span>`;
  }).join('')}</div>`;
}

function renderMemory(detail) {
  const brief = detail.brief || {};
  const source = brief.source_status || {};
  const reference = source.freshness_reference_date ? `资料更新至 ${source.freshness_reference_date}` : '';
  const history = source.historical_fact_count ? `${source.historical_fact_count} 条历史记录已转入周度追溯` : '';
  els.projectMemory.innerHTML = `
    <div class="memory-row stage-row"><div class="memory-label">当前阶段</div><div class="memory-value stage-value">${escapeHtml(brief.current_stage || '尚未识别')}</div>${reference ? `<div class="memory-source">${escapeHtml(reference)}</div>` : ''}</div>
    <div class="memory-row"><div class="memory-label">已完成</div>${memoryTags(brief.completed)}</div>
    <div class="memory-row"><div class="memory-label">进行中</div>${memoryTags(brief.in_progress)}</div>
    <div class="memory-row"><div class="memory-label">当前问题</div>${memoryTags(brief.issues, true)}</div>
    <div class="memory-row"><div class="memory-label">下一步</div>${memoryTags(brief.next_steps)}</div>
    <div class="memory-row"><div class="memory-label">最新指标</div>${memoryTags(brief.latest_metrics, false, 5)}</div>
    ${history ? `<div class="history-note">${escapeHtml(history)}</div>` : ''}`;
}

function renderContributors(detail) {
  const contributors = detail.contributors?.contributors || [];
  if (!contributors.length) {
    els.contributors.innerHTML = '<div class="empty">暂无人员数据</div>';
    return;
  }
  els.contributors.innerHTML = `<div class="contributor-grid">${contributors.slice(0, 20).map(item => {
    const agents = (item.agents || []).map(agent => typeof agent === 'string' ? agent : (agent.name || agent.agent_name)).filter(Boolean);
    const branches = Array.isArray(item.branches) ? item.branches : Object.keys(item.branches || {});
    const sourceTypes = item.source_types || [];
    const sourceLabels = [];
    if (sourceTypes.includes('local')) sourceLabels.push('<span class="source-pill local">本机接入</span>');
    if (sourceTypes.includes('agent')) sourceLabels.push('<span class="source-pill agent">智能体</span>');
    if (sourceTypes.includes('repository')) sourceLabels.push('<span class="source-pill repo">仓库参与</span>');
    return `
      <div class="contributor-card">
        <div class="contributor-head"><span>${escapeHtml(item.display_name || item.user_id || item.name || '未知用户')}</span>${item.dirty_workspace_count ? `<span class="badge warn">${item.dirty_workspace_count} 待提交</span>` : ''}</div>
        <div class="source-pills">${sourceLabels.join('')}</div>
        <div class="contributor-meta">
          ${agents.length ? `<span>${escapeHtml(agents.join(' / '))}</span>` : ''}
          ${branches.length ? `<span>分支 ${escapeHtml(branches.slice(0, 3).join(' / '))}</span>` : ''}
          ${item.remote_event_count ? `<span>${item.remote_event_count} 条仓库活动</span>` : ''}
        </div>
      </div>`;
  }).join('')}</div>${contributors.length > 20 ? `<div class="table-footnote">另有 ${contributors.length - 20} 名历史参与人员未展开。</div>` : ''}`;
}

function eventTime(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit' });
}

function actorFromRemote(event) {
  const data = event.data || {};
  const actor = data.author || data.author_name || data.author_username || '';
  return typeof actor === 'object' ? (actor.username || actor.name || '') : actor;
}

function agentActivity(event) {
  const title = event.task_title || event.data?.summary || event.data?.blocker || '开发事项';
  const mapping = {
    'task.started': '开始处理',
    'task.progress': '更新进展',
    'task.finished': '完成开发',
    'test.result': '测试结果',
    'blocker.reported': '发现问题',
  };
  return {
    time: event.observed_at,
    type: 'agent',
    title: `${event.user_id || '开发人员'} · ${mapping[event.event_type] || '开发进展'}：${title}`,
    detail: event.data?.summary || event.data?.blocker || '',
  };
}

function remoteActivity(event) {
  const mapping = {
    'git.push': '已推送代码',
    'git.commit': '提交代码',
    'merge_request.opened': '提交合并申请',
    'merge_request.closed': '关闭合并申请',
    'merge_request.merged': '代码已合并',
    'ci.running': '自动检查进行中',
    'ci.passed': '自动检查通过',
    'ci.failed': '自动检查失败',
    'ci.finished': '自动检查结束',
    'deployment.succeeded': '部署完成',
    'deployment.failed': '部署失败',
  };
  const label = mapping[event.event_type] || '项目更新';
  const name = event.data?.title || event.task_title || event.branch || '';
  const actor = actorFromRemote(event);
  const prefix = actor ? `${actor} · ` : '';
  const detail = [event.branch ? `分支 ${event.branch}` : '', event.repository_id || ''].filter(Boolean).join(' · ');
  return {
    time: event.observed_at,
    type: 'remote',
    title: `${prefix}${label}${name ? `：${name}` : ''}`,
    detail,
  };
}

function localSignature(snap) {
  const git = snap.payload?.git || {};
  const repositories = git.repositories || [];
  const normalized = repositories.length ? repositories : [git];
  return normalized.map(repo => [
    repo.repository_id || repo.repository_path || '',
    repo.branch || '',
    Boolean(repo.dirty),
    repo.ahead ?? '',
    repo.behind ?? '',
    JSON.stringify(repo.change_counts || {}),
  ].join(':')).sort().join('|');
}

function localActivity(snap) {
  const git = snap.payload?.git || {};
  const repositories = git.repositories || [];
  const normalized = repositories.length ? repositories : [git];
  const dirty = normalized.filter(repo => repo.dirty).length;
  const branches = [...new Set(normalized.map(repo => repo.branch).filter(Boolean))];
  const changed = normalized.reduce((sum, repo) => sum + (repo.changed_files?.length || 0), 0);
  const title = dirty ? `${snap.user_id || '开发人员'} · 本地修改待提交` : `${snap.user_id || '开发人员'} · 本地状态更新`;
  const detail = [branches.join(' / '), changed ? `${changed} 个文件有变化` : '', dirty ? `${dirty} 个仓库待提交` : ''].filter(Boolean).join(' · ');
  return { time: snap.observed_at, type: 'local', title, detail };
}

function buildTimeline(detail) {
  const items = [];
  for (const event of detail.agentEvents || []) items.push(agentActivity(event));

  const pushedShas = new Set(
    (detail.remoteEvents || [])
      .filter(event => event.event_type === 'git.push' && event.commit_sha)
      .map(event => String(event.commit_sha))
  );
  const remoteSeen = new Set();
  for (const event of detail.remoteEvents || []) {
    if (event.event_type === 'git.commit' && event.commit_sha && pushedShas.has(String(event.commit_sha))) continue;
    const identity = [event.event_type, event.repository_id, event.commit_sha, event.branch, event.data?.pipeline_id, event.data?.iid].join('|');
    if (remoteSeen.has(identity)) continue;
    remoteSeen.add(identity);
    items.push(remoteActivity(event));
  }

  const snapshotHistory = [...(detail.snapshots || [])].sort((a, b) => new Date(a.observed_at || 0) - new Date(b.observed_at || 0));
  const lastByWorkspace = new Map();
  for (const snap of snapshotHistory) {
    const workspaceKey = [snap.user_id, snap.device_id, snap.workspace_name].join('|');
    const signature = localSignature(snap);
    if (lastByWorkspace.get(workspaceKey) === signature) continue;
    lastByWorkspace.set(workspaceKey, signature);
    items.push(localActivity(snap));
  }

  return items.sort((a, b) => new Date(b.time || 0) - new Date(a.time || 0)).slice(0, 100);
}

function weekStart(dateValue) {
  const date = new Date(dateValue);
  if (Number.isNaN(date.getTime())) return null;
  const local = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const day = (local.getDay() + 6) % 7;
  local.setDate(local.getDate() - day);
  return local;
}

function dateKey(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function weekLabel(startKey, index) {
  const start = new Date(`${startKey}T00:00:00`);
  const end = new Date(start);
  end.setDate(end.getDate() + 6);
  const range = `${start.getMonth() + 1}月${start.getDate()}日 – ${end.getMonth() + 1}月${end.getDate()}日`;
  const current = weekStart(new Date());
  if (startKey === dateKey(current)) return `本周 · ${range}`;
  current.setDate(current.getDate() - 7);
  if (startKey === dateKey(current)) return `上周 · ${range}`;
  return range;
}

function groupTimelineByWeek(items) {
  const groups = new Map();
  for (const item of items) {
    const start = weekStart(item.time);
    if (!start) continue;
    const key = dateKey(start);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  }
  return [...groups.entries()].sort((a, b) => b[0].localeCompare(a[0]));
}

function weeklySummaryMap(detail) {
  const map = new Map();
  for (const week of detail.brief?.weekly_progress || []) {
    map.set(week.start, week);
  }
  return map;
}

function renderWeekSummary(week) {
  if (!week) return '';
  const stats = [];
  if (week.commit_count) stats.push(`${week.commit_count} 次提交`);
  if (week.merge_count) stats.push(`${week.merge_count} 次合并`);
  if (week.ci_failure_count) stats.push(`${week.ci_failure_count} 次检查失败`);
  const rows = [];
  if ((week.completed || []).length) rows.push(`<div class="week-summary-row"><span>完成</span><div>${week.completed.slice(0, 3).map(item => `<em>${escapeHtml(item)}</em>`).join('')}</div></div>`);
  if ((week.issues || []).length) rows.push(`<div class="week-summary-row issues"><span>问题</span><div>${week.issues.slice(0, 3).map(item => `<em>${escapeHtml(item)}</em>`).join('')}</div></div>`);
  if ((week.metrics || []).length) rows.push(`<div class="week-summary-row"><span>指标</span><div>${week.metrics.slice(0, 3).map(item => `<em>${escapeHtml(item)}</em>`).join('')}</div></div>`);
  if (!rows.length && !stats.length) return '';
  return `<div class="week-summary">${stats.length ? `<div class="week-stats">${stats.map(item => `<span>${escapeHtml(item)}</span>`).join('')}</div>` : ''}${rows.join('')}</div>`;
}

function renderTimeline(detail) {
  const items = buildTimeline(detail);
  const eventGroups = groupTimelineByWeek(items);
  const summaryMap = weeklySummaryMap(detail);
  const allStarts = new Set([...eventGroups.map(([key]) => key), ...summaryMap.keys()]);
  const starts = [...allStarts].sort().reverse().slice(0, 10);
  els.timelineCount.textContent = `${starts.length} 周`;
  if (!starts.length) {
    els.timeline.innerHTML = '<div class="empty">暂无周度进展</div>';
    return;
  }
  const eventMap = new Map(eventGroups);
  els.timeline.innerHTML = starts.map((startKey, index) => {
    const weekItems = eventMap.get(startKey) || [];
    const visible = weekItems.slice(0, 10);
    const hidden = weekItems.length - visible.length;
    return `
      <section class="week-section">
        <div class="week-header"><div><strong>${escapeHtml(weekLabel(startKey, index))}</strong><span>${weekItems.length} 条动态</span></div></div>
        ${renderWeekSummary(summaryMap.get(startKey))}
        <div class="week-events">
          ${visible.map(item => `
            <div class="timeline-item">
              <div class="timeline-time">${escapeHtml(eventTime(item.time))}</div>
              <div class="timeline-dot ${item.type}"></div>
              <div><div class="timeline-title">${escapeHtml(item.title)}</div><div class="timeline-detail">${escapeHtml(item.detail || '')}</div></div>
            </div>`).join('')}
          ${hidden > 0 ? `<div class="week-more">另有 ${hidden} 条低优先级动态未展开</div>` : ''}
        </div>
      </section>`;
  }).join('');
}

async function loadProject(projectId) {
  const encoded = encodeURIComponent(projectId);
  const paths = {
    current: 'current', brief: 'brief', tasks: 'tasks', contributors: 'contributors',
    agentEvents: 'agent-events?limit=100', remoteEvents: 'remote-events?limit=500', snapshots: 'snapshots?limit=120',
  };
  const detail = { errors: [] };
  await Promise.all(Object.entries(paths).map(async ([key, path]) => {
    try { detail[key] = await api(`/api/v1/projects/${encoded}/${path}`); }
    catch (error) { detail.errors.push(key); }
  }));
  if (detail.errors.length === Object.keys(paths).length) throw new Error('项目接口暂不可用');
  return detail;
}

async function selectProject(projectId) {
  document.getElementById('news-view')?.classList.add('hidden');
  document.getElementById('news-nav')?.classList.remove('active');
  const requestId = ++state.projectLoadId;
  state.detail = null;
  state.selectedProjectId = projectId;
  els.portfolioNav.classList.remove('active');
  els.portfolioView.classList.add('hidden');
  document.getElementById('settings-view')?.classList.add('hidden');
  document.getElementById('settings-nav')?.classList.remove('active');
  document.getElementById('intelligence-view')?.classList.add('hidden');
  document.getElementById('dashboard-view')?.classList.remove('hidden');
  renderProjectList();
  const project = state.projects.find(item => item.project_id === projectId) || {};
  els.title.textContent = projectLabel(project);
  els.subtitle.textContent = '';
  els.overview.innerHTML = metric('项目状态', '正在加载', '正在读取项目进展', true);
  els.taskTable.innerHTML = '<div class="empty">正在加载当前任务…</div>';
  els.projectMemory.innerHTML = '<div class="empty">正在加载项目进展…</div>';
  els.contributors.innerHTML = '<div class="empty">正在加载人员协作…</div>';
  els.timeline.innerHTML = '<div class="empty">正在加载每周进展…</div>';
  try {
    const detail = await loadProject(projectId);
    if (state.selectedProjectId !== projectId || state.projectLoadId !== requestId) return;
    state.detail = detail;
    renderOverview(project, state.detail);
    renderTasks(state.detail);
    renderMemory(state.detail);
    renderContributors(state.detail);
    renderTimeline(state.detail);
    if (detail.errors.length) {
      els.subtitle.textContent = '部分来源暂不可用，已保留可读取的内容。点击刷新重试。';
      if (detail.errors.includes('brief')) {
        els.projectMemory.innerHTML = '<div class="empty">项目进展暂时读取失败，请刷新重试。</div>';
        els.overview.innerHTML = metric('项目概况', '暂不可用', '其他已读取的内容仍可查看', true);
      }
      if (detail.errors.includes('tasks')) els.taskTable.innerHTML = '<div class="empty">任务暂时读取失败，并非没有任务。</div>';
      if (detail.errors.includes('contributors')) els.contributors.innerHTML = '<div class="empty">人员信息暂时读取失败。</div>';
      if (detail.errors.some(key => ['agentEvents', 'remoteEvents', 'snapshots'].includes(key))) {
        els.timeline.insertAdjacentHTML('afterbegin', '<div class="empty">部分活动来源读取失败，以下为已读取的记录。</div>');
      }
    }
  } catch (error) {
    if (state.selectedProjectId !== projectId || state.projectLoadId !== requestId) return;
    els.overview.innerHTML = metric('项目状态', '加载失败', '请点击“刷新数据”重试', true);
    els.taskTable.innerHTML = '<div class="empty">当前任务加载失败</div>';
    els.projectMemory.innerHTML = '<div class="empty">项目进展加载失败</div>';
    els.contributors.innerHTML = '<div class="empty">人员协作加载失败</div>';
    els.timeline.innerHTML = '<div class="empty">每周进展加载失败</div>';
    showToast(`加载项目失败：${error.message}`, true);
  }
}

async function bootstrap() {
  if (!state.projects.length) {
    els.projectList.innerHTML = '<div class="empty">正在加载项目…</div>';
    els.title.textContent = '正在加载项目';
    els.overview.innerHTML = metric('项目状态', '正在加载', '正在连接项目数据', true);
    els.taskTable.innerHTML = '<div class="empty">正在加载当前任务…</div>';
    els.projectMemory.innerHTML = '<div class="empty">正在加载项目进展…</div>';
    els.contributors.innerHTML = '<div class="empty">正在加载人员协作…</div>';
    els.timeline.innerHTML = '<div class="empty">正在加载每周进展…</div>';
  }
  let healthOk = false;
  try {
    await api('/health');
    healthOk = true;
    els.apiState.className = 'health-dot ok';
    els.apiStateText.textContent = '服务正常';
    state.projects = await api('/api/v1/projects');
    renderProjectList();
    if (document.getElementById('news-nav')?.classList?.contains('active')) return true;
    if (state.selectedProjectId && state.projects.some(item => item.project_id === state.selectedProjectId)) {
      await selectProject(state.selectedProjectId);
    } else {
      await showPortfolio();
    }
    return true;
  } catch (error) {
    els.apiState.className = 'health-dot error';
    els.apiStateText.textContent = healthOk ? '项目数据读取失败' : '服务不可用';
    if (!state.projects.length) {
      els.projectList.innerHTML = '<div class="empty">项目加载失败，请点击“刷新数据”重试。</div>';
      els.title.textContent = '项目加载失败';
      els.overview.innerHTML = metric('项目状态', '加载失败', '请点击“刷新数据”重试', true);
      els.taskTable.innerHTML = '<div class="empty">当前任务加载失败</div>';
      els.projectMemory.innerHTML = '<div class="empty">项目进展加载失败</div>';
      els.contributors.innerHTML = '<div class="empty">人员协作加载失败</div>';
      els.timeline.innerHTML = '<div class="empty">每周进展加载失败</div>';
      els.portfolioStatus.textContent = '项目列表读取失败';
      els.portfolioGrid.innerHTML = '<div class="portfolio-empty">连接失败，请点击“刷新数据”重试。</div>';
    }
    showToast(`连接服务失败：${error.message}`, true);
    return false;
  }
}

els.refresh.addEventListener('click', async () => {
  clearReadCache();
  els.refresh.disabled = true;
  try {
    if (await bootstrap()) showToast('数据已刷新');
  } finally {
    els.refresh.disabled = false;
  }
});

els.portfolioNav.addEventListener('click', () => {
  els.portfolioSearch.value = '';
  showPortfolio();
});
els.portfolioSearch.addEventListener('input', renderPortfolio);
els.globalSearchButton.addEventListener('click', () => runGlobalSearch());
document.getElementById('global-search-more').addEventListener('click', () => runGlobalSearch(true));
for (const id of ['global-search-project', 'global-search-source', 'global-search-order']) document.getElementById(id).addEventListener('change', () => { if (els.globalSearchInput.value.trim()) runGlobalSearch(); });
els.globalSearchInput.addEventListener('keydown', event => { if (event.key === 'Enter') runGlobalSearch(); });
els.portfolioRefresh.addEventListener('click', async () => {
  clearReadCache();
  els.portfolioRefresh.disabled = true;
  try {
    if (await bootstrap()) showToast('数据已刷新');
  } finally {
    els.portfolioRefresh.disabled = false;
  }
});

for (const id of ['portfolio-attention', 'portfolio-sort']) document.getElementById(id).addEventListener('change', renderPortfolio);
document.addEventListener('keydown', event => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault();
    showPortfolio();
    els.globalSearchInput.focus();
  }
});
document.getElementById('copy-project-brief').addEventListener('click', async () => {
  const id = state.selectedProjectId;
  const project = state.projects.find(item => item.project_id === id);
  try {
    const brief = await api(`/api/v1/projects/${encodeURIComponent(id)}/brief`);
    const lines = [projectLabel(project || {}), `资料日期：${brief.source_status?.freshness_reference_date || '未知'}`, `当前阶段：${brief.current_stage || '尚未识别'}`];
    for (const [key, label] of [['completed', '已完成'], ['in_progress', '进行中'], ['issues', '问题'], ['next_steps', '下一步'], ['latest_metrics', '指标']]) {
      lines.push(`\n${label}`, ...(brief[key] || []).map(item => `• ${typeof item === 'string' ? item : item.text || item.title || JSON.stringify(item)}`));
      if (!brief[key]?.length) lines.push('尚未识别');
    }
    lines.push('\n依据已采集资料整理，未调用大模型；请结合资料日期核对。');
    await navigator.clipboard.writeText(lines.join('\n'));
    showToast('项目简报已复制，可粘贴到微信或文档');
  } catch (error) { showToast(`复制失败：${error.message}`, true); }
});
for (const id of ['focus-show-handled', 'focus-show-all']) document.getElementById(id).addEventListener('change', () => renderDailyFocus(state.portfolioRows));
window.addEventListener('storage', event => {
  if (event.key === focusStorageKey || event.key === null) renderDailyFocus(state.portfolioRows);
});
// Re-evaluate snoozes when the user returns the next day.
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && !els.portfolioView.classList.contains('hidden')) renderDailyFocus(state.portfolioRows);
});
bootstrap();
