const intelligenceState = {
  projectId: null,
  data: null,
  search: null,
};

const intelligenceEls = {
  view: document.getElementById('intelligence-view'),
  open: document.getElementById('project-intelligence-btn'),
  back: document.getElementById('intelligence-back-btn'),
  title: document.getElementById('intelligence-title'),
  subtitle: document.getElementById('intelligence-subtitle'),
  status: document.getElementById('intelligence-status'),
  summary: document.getElementById('intelligence-summary'),
  context: document.getElementById('intelligence-context'),
  progress: document.getElementById('intelligence-progress'),
  repositories: document.getElementById('intelligence-repositories'),
  categories: document.getElementById('intelligence-categories'),
  series: document.getElementById('intelligence-series'),
  changes: document.getElementById('intelligence-changes'),
  health: document.getElementById('intelligence-health'),
  searchInput: document.getElementById('intelligence-search-input'),
  searchType: document.getElementById('intelligence-search-type'),
  currentOnly: document.getElementById('intelligence-current-only'),
  searchButton: document.getElementById('intelligence-search-btn'),
  searchStatus: document.getElementById('intelligence-search-status'),
  searchResults: document.getElementById('intelligence-search-results'),
};

function intelligenceDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

function intelligenceStatusLabel(status) {
  return {
    current: '当前版本',
    historical: '历史版本',
    latest_period: '最新一期',
    period_history: '历史期次',
    primary: '主文件',
    active_related: '有效关联材料',
    single: '单份材料',
  }[status] || status || '未判断';
}

function intelligenceStatusTone(status) {
  if (['current', 'latest_period', 'primary', 'single'].includes(status)) return 'good';
  if (status === 'active_related') return 'info';
  if (['historical', 'period_history'].includes(status)) return 'neutral';
  return 'neutral';
}

function intelligenceListText(value, key = 'fact') {
  if (typeof value === 'string') return value;
  if (!value || typeof value !== 'object') return String(value ?? '');
  return value[key] || value.text || value.summary || value.title || value.name || JSON.stringify(value);
}

function intelligencePills(items, key = 'fact', limit = 8) {
  if (!items?.length) return '<span class="muted">暂无</span>';
  return `<div class="context-pills">${items.slice(0, limit).map(item => (
    `<span class="context-pill" title="${escapeHtml(intelligenceListText(item, key))}">${escapeHtml(intelligenceListText(item, key))}</span>`
  )).join('')}</div>`;
}

function showIntelligenceView() {
  if (!state.selectedProjectId) {
    showToast('请先选择一个项目', true);
    return;
  }
  document.getElementById('settings-view')?.classList.add('hidden');
  document.getElementById('dashboard-view')?.classList.add('hidden');
  intelligenceEls.view?.classList.remove('hidden');
  loadProjectIntelligence(state.selectedProjectId).catch(error => {
    intelligenceEls.status.textContent = '加载失败';
    intelligenceEls.status.className = 'badge bad';
    showToast(`项目认知加载失败：${error.message}`, true);
  });
}

function hideIntelligenceView() {
  intelligenceEls.view?.classList.add('hidden');
  document.getElementById('settings-view')?.classList.add('hidden');
  document.getElementById('dashboard-view')?.classList.remove('hidden');
}

function renderIntelligenceSummary(data) {
  const summary = data.summary || {};
  const context = data.context || {};
  const cards = [
    ['项目材料', summary.material_count || 0],
    ['材料系列', summary.series_count || 0],
    ['多版本材料', summary.multi_version_series_count || 0],
    ['可搜正文', summary.search_indexed_file_count || 0],
    ['待确认问题', summary.health_issue_count || 0],
  ];
  intelligenceEls.summary.innerHTML = cards.map(([label, value]) => `
    <div class="intelligence-summary-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>
  `).join('');

  const project = { ...(data.profile || {}), ...(context.project || {}) };
  const purpose = project.purpose || project.description || '尚未录入项目背景；平台已根据本机材料和代码活动建立项目索引。';
  const currentStage = project.current_stage || '尚未明确';
  intelligenceEls.context.innerHTML = `
    <div class="context-purpose"><strong>项目用途</strong><br>${escapeHtml(purpose)}</div>
    <div class="context-grid">
      <div class="context-block"><strong>当前阶段</strong>${intelligencePills([currentStage], 'fact', 1)}</div>
      <div class="context-block"><strong>当前工作</strong>${intelligencePills(context.current_work, 'fact')}</div>
      <div class="context-block"><strong>已知问题</strong>${intelligencePills(context.known_issues, 'fact')}</div>
      <div class="context-block"><strong>开发侧 AI 已知事实</strong>${intelligencePills(context.known_facts, 'fact')}</div>
    </div>`;
}

function progressItems(items, emptyText) {
  if (!items?.length) return `<div class="intelligence-empty compact-empty">${escapeHtml(emptyText)}</div>`;
  return `<ul class="progress-list">${items.slice(0, 6).map(item => `<li>${escapeHtml(intelligenceListText(item))}</li>`).join('')}</ul>`;
}

function renderProgress(data) {
  const progress = data.progress || {};
  const stage = progress.current_stage || '尚未形成明确阶段';
  intelligenceEls.progress.innerHTML = `
    <div class="progress-stage"><span>当前阶段</span><strong>${escapeHtml(stage)}</strong></div>
    <div class="progress-section"><strong>已完成</strong>${progressItems(progress.completed, '暂无可确认的已完成事项')}</div>
    <div class="progress-section"><strong>进行中</strong>${progressItems(progress.in_progress, '当前没有已识别的明确任务')}</div>
    <div class="progress-section"><strong>待处理问题</strong>${progressItems(progress.issues, '当前没有来自项目资料的待处理问题')}</div>
    <div class="progress-section"><strong>下一步</strong>${progressItems(progress.next_steps, '尚未从资料中识别下一步')}</div>`;
}

function repositoryLabel(repository) {
  const id = repository.id || '未命名仓库';
  const role = repository.role ? ` · ${repository.role}` : '';
  return `${id}${role}`;
}

function renderRepositories(data) {
  const repositories = data.profile?.repositories || [];
  if (!repositories.length) {
    intelligenceEls.repositories.innerHTML = '<div class="intelligence-empty">尚未采集到代码仓库；可在平台配置中绑定本机目录或远端仓库。</div>';
    return;
  }
  intelligenceEls.repositories.innerHTML = `<div class="repository-list">${repositories.map(repository => {
    const provider = repository.provider || '本机';
    const branch = repository.branch || '未识别分支';
    const head = repository.head ? String(repository.head).slice(0, 10) : '未识别 SHA';
    const sync = repository.ahead || repository.behind ? `领先 ${repository.ahead || 0} / 落后 ${repository.behind || 0}` : '与上游同步';
    const worktree = repository.dirty ? '有本地修改' : '工作区干净';
    return `<div class="repository-item">
      <div><strong>${escapeHtml(repositoryLabel(repository))}</strong><div class="intelligence-list-path">${escapeHtml(repository.url || '未记录远端地址')}</div></div>
      <div class="repository-meta"><span>${escapeHtml(provider)}</span><span>${escapeHtml(branch)} · ${escapeHtml(head)}</span><span>${escapeHtml(sync)} · ${escapeHtml(worktree)}</span></div>
    </div>`;
  }).join('')}</div>`;
}

function renderMaterialCategories(data) {
  const categories = data.material_categories || [];
  intelligenceEls.searchType.innerHTML = '<option value="">全部材料</option>' + categories.map(item => (
    `<option value="${escapeHtml(item.type)}">${escapeHtml(item.label)}（${item.count || 0}）</option>`
  )).join('');
  if (!categories.length) {
    intelligenceEls.categories.innerHTML = '<div class="intelligence-empty">尚未识别到材料分类</div>';
    return;
  }
  intelligenceEls.categories.innerHTML = `<div class="material-category-grid">${categories.slice(0, 15).map(item => `
    <div class="material-category"><span>${escapeHtml(item.label)}</span><strong>${item.count || 0}</strong></div>
  `).join('')}</div>`;
}

function renderSeries(data) {
  const series = [...(data.series || [])].sort((a, b) => {
    const aMulti = Number(a.count || 0) > 1 ? 1 : 0;
    const bMulti = Number(b.count || 0) > 1 ? 1 : 0;
    return bMulti - aMulti || Number(b.count || 0) - Number(a.count || 0);
  });
  if (!series.length) {
    intelligenceEls.series.innerHTML = '<div class="intelligence-empty">尚未形成材料系列</div>';
    return;
  }
  intelligenceEls.series.innerHTML = `<div class="intelligence-list">${series.slice(0, 40).map(item => {
    const evidence = (item.evidence || []).join('；');
    const current = item.current_path || '-';
    return `<div class="intelligence-list-item">
      <div class="intelligence-list-main">
        <div class="intelligence-list-title"><strong>${escapeHtml(item.title || '未命名材料')}</strong><span class="badge ${Number(item.count || 0) > 1 ? 'info' : 'neutral'}">${item.count || 0} 份</span></div>
        <div class="intelligence-list-path">当前/主材料：${escapeHtml(current)}</div>
        ${evidence ? `<div class="intelligence-list-note">判断依据：${escapeHtml(evidence)}</div>` : ''}
      </div>
      <div class="intelligence-list-meta"><span>${escapeHtml(item.material_type_label || '其他资料')}</span><span>${escapeHtml(item.source === 'agent_context' ? '开发侧AI认知' : item.source === 'project_memory' ? '项目记忆' : '平台自动归类')}</span></div>
    </div>`;
  }).join('')}</div>`;
}

function changeLabel(type) {
  return {
    added: '新增',
    removed: '移除',
    modified: '修改',
    context_updated: '项目认知更新',
    recently_modified: '近期修改',
  }[type] || type || '变化';
}

function renderRecentChanges(data) {
  const changes = data.recent_changes || [];
  if (!changes.length) {
    intelligenceEls.changes.innerHTML = '<div class="intelligence-empty">暂无材料变化记录</div>';
    return;
  }
  intelligenceEls.changes.innerHTML = `<div class="intelligence-list">${changes.slice(0, 30).map(item => `
    <div class="intelligence-list-item">
      <div class="intelligence-list-main">
        <div class="intelligence-list-title"><strong>${escapeHtml(item.name || item.path || '材料变化')}</strong><span class="badge info">${escapeHtml(changeLabel(item.change_type))}</span></div>
        <div class="intelligence-list-path">${escapeHtml(item.path || '')}</div>
      </div>
      <div class="intelligence-list-meta"><span>${escapeHtml(item.material_type_label || '')}</span><span>${escapeHtml(intelligenceDate(item.observed_at || item.modified_at))}</span></div>
    </div>`).join('')}</div>`;
}

function healthLabel(type) {
  return {
    context_missing: '项目认知尚未建立',
    context_file_missing: '认知文件与实际材料不一致',
    context_stale: '项目认知需要更新',
    workspace_divergence: '不同开发电脑材料不一致',
    duplicate_content: '发现重复材料',
  }[type] || '待确认';
}

function renderHealth(data) {
  const health = data.health || {};
  const issues = health.issues || [];
  if (!issues.length) {
    intelligenceEls.health.innerHTML = '<div class="intelligence-health-item"><strong>材料状态正常</strong>当前未识别到明显的版本冲突、工作区差异或重复材料问题。</div>';
    return;
  }
  intelligenceEls.health.innerHTML = issues.slice(0, 30).map(item => `
    <div class="intelligence-health-item"><strong>${escapeHtml(healthLabel(item.type))}</strong>${escapeHtml(item.message || '')}${item.path ? `<div class="intelligence-list-path">${escapeHtml(item.path)}</div>` : ''}</div>
  `).join('');
}

function renderSearchResults(payload) {
  intelligenceState.search = payload;
  const results = payload.results || [];
  const contentHint = payload.content_search_available
    ? `已建立 ${payload.search_indexed_file_count || 0} 份材料正文索引，可定位正文位置。`
    : '当前可搜索文件名、路径、用途和已抽取摘要；若需正文定位，请在平台配置中启用“本机读取资料内容”。';
  intelligenceEls.searchStatus.textContent = `找到 ${payload.count || 0} 项。${contentHint}`;
  if (!results.length) {
    intelligenceEls.searchResults.innerHTML = '<div class="intelligence-empty">没有找到匹配材料。可以尝试文件名、编号、金额、功能名称、合同条款或正文关键词。</div>';
    return;
  }
  intelligenceEls.searchResults.innerHTML = results.map(item => {
    const material = item.material || {};
    const locator = item.locator ? `命中位置：${item.locator}` : '';
    const purpose = material.purpose ? `用途：${material.purpose}` : '';
    return `<div class="search-result">
      <div class="search-result-head">
        <div class="search-result-title">
          <strong>${escapeHtml(material.name || material.path || '未命名材料')}</strong>
          <div class="search-result-path">${escapeHtml(material.path || '')}</div>
        </div>
        <div><span class="badge ${intelligenceStatusTone(material.version_status)}">${escapeHtml(intelligenceStatusLabel(material.version_status))}</span></div>
      </div>
      ${item.snippet ? `<div class="search-result-snippet">${escapeHtml(item.snippet)}</div>` : ''}
      <div class="search-result-footer">
        <span>${escapeHtml(material.material_type_label || '其他资料')}</span>
        ${locator ? `<span>${escapeHtml(locator)}</span>` : ''}
        ${purpose ? `<span>${escapeHtml(purpose)}</span>` : ''}
        <span>最近修改 ${escapeHtml(intelligenceDate(material.modified_at))}</span>
        <button class="copy-path-button" type="button" data-copy-path="${escapeHtml(material.path || '')}">复制路径</button>
      </div>
    </div>`;
  }).join('');
  intelligenceEls.searchResults.querySelectorAll('[data-copy-path]').forEach(button => {
    button.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(button.dataset.copyPath || '');
        showToast('文件路径已复制');
      } catch (_error) {
        showToast('浏览器未允许复制，请手动复制路径', true);
      }
    });
  });
}

async function runIntelligenceSearch() {
  const projectId = intelligenceState.projectId || state.selectedProjectId;
  const query = intelligenceEls.searchInput.value.trim();
  if (!projectId || !query) {
    intelligenceEls.searchStatus.textContent = '请输入要查找的文件名、编号、金额、功能或正文关键词。';
    return;
  }
  intelligenceEls.searchButton.disabled = true;
  intelligenceEls.searchButton.textContent = '搜索中...';
  try {
    const params = new URLSearchParams({ q: query, limit: '50' });
    if (intelligenceEls.searchType.value) params.set('material_type', intelligenceEls.searchType.value);
    if (intelligenceEls.currentOnly.checked) params.set('current_only', 'true');
    const payload = await api(`/api/v1/projects/${encodeURIComponent(projectId)}/search?${params.toString()}`);
    renderSearchResults(payload);
  } catch (error) {
    intelligenceEls.searchStatus.textContent = `搜索失败：${error.message}`;
    intelligenceEls.searchResults.innerHTML = '';
  } finally {
    intelligenceEls.searchButton.disabled = false;
    intelligenceEls.searchButton.textContent = '搜索';
  }
}

async function loadProjectIntelligence(projectId) {
  intelligenceState.projectId = projectId;
  const project = state.projects.find(item => item.project_id === projectId) || {};
  intelligenceEls.title.textContent = `${projectLabel(project)} · 项目认知`;
  intelligenceEls.subtitle.textContent = '理解项目材料、版本关系、最近变化，并直接搜索文件内容中的关键信息';
  intelligenceEls.status.textContent = '加载中';
  intelligenceEls.status.className = 'badge neutral';
  const data = await api(`/api/v1/projects/${encodeURIComponent(projectId)}/intelligence`);
  intelligenceState.data = data;
  renderIntelligenceSummary(data);
  renderProgress(data);
  renderRepositories(data);
  renderMaterialCategories(data);
  renderSeries(data);
  renderRecentChanges(data);
  renderHealth(data);
  const contextAvailable = data.context?.available;
  intelligenceEls.status.textContent = contextAvailable ? '项目认知已接入' : '自动理解中';
  intelligenceEls.status.className = `badge ${contextAvailable ? 'good' : 'warn'}`;
  intelligenceEls.searchStatus.textContent = (data.summary?.search_indexed_file_count || 0)
    ? `已索引 ${data.summary.search_indexed_file_count} 份材料正文。输入关键词可定位到页、Sheet/行、段落或文本行。`
    : '输入关键词可先搜索文件名、路径、用途和摘要。';
  intelligenceEls.searchResults.innerHTML = '';
}

intelligenceEls.open?.addEventListener('click', showIntelligenceView);
intelligenceEls.back?.addEventListener('click', hideIntelligenceView);
intelligenceEls.searchButton?.addEventListener('click', runIntelligenceSearch);
intelligenceEls.searchInput?.addEventListener('keydown', event => {
  if (event.key === 'Enter') runIntelligenceSearch();
});

document.addEventListener('click', event => {
  if (event.target.closest?.('[data-project-id]')) {
    intelligenceEls.view?.classList.add('hidden');
  }
});
