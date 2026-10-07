const intelligenceState = {
  projectId: null,
  data: null,
  search: null,
  loadId: 0,
  searchId: 0,
};

const intelligenceEls = {
  view: document.getElementById('intelligence-view'),
  open: document.getElementById('project-intelligence-btn'),
  back: document.getElementById('intelligence-back-btn'),
  title: document.getElementById('intelligence-title'),
  subtitle: document.getElementById('intelligence-subtitle'),
  status: document.getElementById('intelligence-status'),
  summary: document.getElementById('intelligence-summary'),
  dossier: document.getElementById('intelligence-dossier'),
  dossierSettings: document.getElementById('dossier-settings-btn'),
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

function dossierDate(value) {
  if (!value) return '时间未知';
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '时间未知';
  return date.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
}

function dossierAgeDays(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : Math.max(0, Math.floor((Date.now() - date.getTime()) / 86400000));
}

function dossierSourceLink(source) {
  if (!source) return '未标原始链接';
  try {
    const url = new URL(source);
    if (url.protocol === 'https:' || url.protocol === 'http:') {
      return `<a href="${escapeHtml(url.href)}" target="_blank" rel="noopener noreferrer">查看来源（${escapeHtml(url.hostname)}）</a>`;
    }
  } catch (_error) {
    // Local paths are displayed as text; browsers cannot safely open host files.
  }
  return escapeHtml(source);
}

function dossierFacts(data) {
  const facts = [];
  const seen = new Set();
  const add = item => {
    const text = String(item.text || '').replace(/^\s*[-*•]\s*/, '').trim();
    if (!text || seen.has(text)) return;
    seen.add(text);
    facts.push({ ...item, text });
  };
  for (const fact of data.context?.known_facts || []) {
    add({ text: intelligenceListText(fact), source: fact.source, date: data.context?.generated_at, observed: data.profile?.observed_at, label: '项目认知记录' });
  }
  const materials = [...(data.materials || [])]
    .filter(item => !['historical', 'period_history'].includes(item.version_status))
    .sort((a, b) => String(b.modified_at || '').localeCompare(String(a.modified_at || '')));
  for (const material of materials) {
    for (const fact of (material.facts || []).slice(0, 2)) {
      add({ text: intelligenceListText(fact, 'text'), source: material.path, date: material.modified_at, observed: material.observed_at, label: '材料摘录' });
    }
    if (facts.length >= 8) break;
  }
  return facts.slice(0, 5);
}

function renderDossier(data) {
  const profile = data.profile || {};
  const context = data.context || {};
  const project = context.project || {};
  const progress = data.progress || {};
  const sourceDate = context.available && project.current_stage
    ? context.modified_at || context.generated_at
    : progress.source_status?.freshness_reference_date;
  const sourceAge = dossierAgeDays(sourceDate);
  const stage = project.current_stage || progress.current_stage || '尚未识别';
  const progressStage = progress.current_stage;
  const stageSource = project.current_stage ? '项目认知文件' : '项目资料自动推断，依据见下方';
  const stageBasis = progress.current_stage_basis || {};
  const stageEvidence = (stageBasis.evidence || []).filter(item => item.text).slice(0, 3);
  const stageEvidenceHtml = `<div class="dossier-stage-basis"><strong>${escapeHtml(project.current_stage ? '自动汇总阶段的推断线索' : '阶段推断线索')}</strong>
    <div>${escapeHtml(stageBasis.reason || '暂无可解释的阶段判断依据')}；这只是资料分类，不代表功能已验收。</div>
    ${stageEvidence.length ? stageEvidence.map(item => `<div class="dossier-stage-evidence"><span>${escapeHtml(item.text)}</span><small>${escapeHtml(item.path || item.repository_id || '任务或代码活动')} · 资料日期 ${escapeHtml(dossierDate(item.source_date))} · 采集 ${escapeHtml(dossierDate(item.observed_at))}</small></div>`).join('') : '<div class="dossier-stage-evidence"><small>尚未关联到逐条材料；请核对项目资料。</small></div>'}</div>`;
  const purpose = project.purpose || profile.description || '尚未登记项目背景';
  const purposeSource = project.purpose
    ? `项目认知文件 · 更新 ${dossierDate(context.modified_at || context.generated_at)} · 本地采集 ${dossierDate(profile.observed_at)}`
    : `本地项目登记 · 采集 ${dossierDate(profile.observed_at)} · 未标原始资料日期`;
  const nextFromContext = (context.current_work || [])[0];
  const rawNext = intelligenceListText(nextFromContext || (progress.next_steps || [])[0] || '尚未识别明确下一步');
  const next = rawNext.replace(/^\s*[-*•]\s*/, '');
  const nextRef = (progress.next_step_evidence || []).find(item => item.text === rawNext) || {};
  const nextDate = nextFromContext ? context.modified_at || context.generated_at : nextRef.source_date || sourceDate;
  const nextAge = dossierAgeDays(nextDate);
  const nextOrigin = nextFromContext ? '.project-intelligence/project_context.yaml' : nextRef.path || '尚未关联原始材料';
  const decisions = (progress.decision_evidence || []).filter(item => item.text).slice(0, 3);
  const facts = dossierFacts(data);
  const materials = [...(data.materials || [])]
    .filter(item => !['historical', 'period_history'].includes(item.version_status))
    .sort((a, b) => String(b.modified_at || '').localeCompare(String(a.modified_at || '')))
    .slice(0, 4);
  intelligenceEls.dossier.innerHTML = `
    <div class="dossier-summary">
      <div class="dossier-field"><div class="dossier-field-label">项目背景</div><div class="dossier-field-value">${escapeHtml(purpose)}</div><div class="dossier-field-source">${escapeHtml(purposeSource)}</div></div>
      <div class="dossier-field"><div class="dossier-field-label">资料中的当前阶段</div><div class="dossier-field-value strong">${escapeHtml(stage)}</div>
        <div class="dossier-field-source${sourceAge === null || sourceAge > 14 ? ' warn' : ''}">${escapeHtml(stageSource)} · 资料日期 ${escapeHtml(dossierDate(sourceDate))} · 本地采集 ${escapeHtml(dossierDate(profile.observed_at))}${sourceAge > 14 ? ` · 距今 ${sourceAge} 天，需核对` : ''}</div>
        ${project.current_stage && progressStage && project.current_stage !== progressStage ? `<div class="dossier-stage-note">自动资料汇总另显示“${escapeHtml(progressStage)}”；两种判断尚未核对一致。</div>` : ''}
        ${stageEvidenceHtml}
      </div>
      <div class="dossier-field"><div class="dossier-field-label">资料中的下一步</div><div class="dossier-field-value">${escapeHtml(next)}</div><div class="dossier-field-source${nextAge === null || nextAge > 14 ? ' warn' : ''}">${escapeHtml(nextOrigin)} · 资料日期 ${escapeHtml(dossierDate(nextDate))} · 本地采集 ${escapeHtml(dossierDate(nextRef.observed_at || profile.observed_at))}${nextAge > 14 ? ` · 距今 ${nextAge} 天，是否仍待办需确认` : ''}</div></div>
      <div class="dossier-field"><div class="dossier-field-label">登记负责人</div><div class="dossier-field-value">${escapeHtml(profile.owner || '未登记')}</div><div class="dossier-field-source">项目档案 · 本地采集 ${escapeHtml(dossierDate(profile.observed_at))}；已关联 ${registeredCodeRepositories(profile.repositories).length} 个仓库</div></div>
    </div>
    <div class="dossier-subgrid">
      <div class="dossier-section"><h4>可追溯的事实摘录</h4><p class="dossier-section-note">记录原始链接或材料路径。摘录不等于已完成验收。</p>
        ${facts.length ? facts.map(item => `<div class="dossier-fact"><div class="dossier-fact-text">${escapeHtml(item.text)}</div><div class="dossier-fact-meta">${escapeHtml(item.label)} · ${dossierSourceLink(item.source)} · 资料日期 ${escapeHtml(dossierDate(item.date))} · 本地采集 ${escapeHtml(dossierDate(item.observed))}</div></div>`).join('') : '<div class="intelligence-empty compact-empty">暂无可逐条追溯的事实；先核对项目资料和绑定。</div>'}
      </div>
      <div class="dossier-section"><h4>最近的项目材料</h4><p class="dossier-section-note">材料修改日期与本机采集日期分开显示；路径可复制。</p>
        ${materials.length ? materials.map(item => `<div class="dossier-material"><div class="dossier-material-head"><strong>${escapeHtml(item.name || item.path || '未命名材料')}</strong><span class="badge ${intelligenceStatusTone(item.version_status)}">${escapeHtml(intelligenceStatusLabel(item.version_status))}</span></div><div class="dossier-material-meta">${escapeHtml(item.material_type_label || '其他资料')} · 修改 ${escapeHtml(dossierDate(item.modified_at))} · 采集 ${escapeHtml(dossierDate(item.observed_at))}</div><div class="dossier-material-meta">${escapeHtml(item.path || '')}</div><button class="dossier-copy" type="button" data-dossier-copy="${escapeHtml(item.path || '')}">复制材料路径</button></div>`).join('') : '<div class="intelligence-empty compact-empty">尚未采集到项目材料。</div>'}
      </div>
    </div>
    <div class="dossier-decisions"><h4>关键决定与依据</h4>
      ${decisions.length ? decisions.map(item => `<div class="dossier-fact"><div class="dossier-fact-text">${escapeHtml(item.text)}</div><div class="dossier-fact-meta">${escapeHtml(item.path || '尚未关联原始材料')} · 资料日期 ${escapeHtml(dossierDate(item.source_date))} · 本地采集 ${escapeHtml(dossierDate(item.observed_at))}</div></div>`).join('') : '<div class="intelligence-empty compact-empty">尚未从项目材料中识别到可追溯的决定。</div>'}
    </div>`;
}

function showIntelligenceView() {
  if (!state.selectedProjectId) {
    showToast('请先选择一个项目', true);
    return;
  }
  document.getElementById('settings-view')?.classList.add('hidden');
  document.getElementById('dashboard-view')?.classList.add('hidden');
  intelligenceEls.view?.classList.remove('hidden');
  const projectId = state.selectedProjectId;
  return loadProjectIntelligence(projectId).catch(error => {
    if (intelligenceState.projectId !== projectId) return;
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

function progressItems(items, emptyText, evidence = []) {
  if (!items?.length) return `<div class="intelligence-empty compact-empty">${escapeHtml(emptyText)}</div>`;
  const list = values => `<ul class="progress-list">${values.map(item => `<li>${escapeHtml(intelligenceListText(item).replace(/^\s*[-*•]\s*/, ''))}${evidence.length ? factEvidenceHtml(intelligenceListText(item), evidence) : ''}</li>`).join('')}</ul>`;
  return list(items.slice(0, 6)) + (items.length > 6
    ? `<details class="progress-more"><summary>展开其余 ${items.length - 6} 项</summary>${list(items.slice(6))}</details>` : '');
}

function renderProgress(data) {
  const progress = data.progress || {};
  const context = data.context?.available === false ? {} : (data.context || {});
  const recordedStage = context.project?.current_stage;
  const inferredStage = progress.current_stage;
  const stage = recordedStage || inferredStage || '尚未形成明确阶段';
  const contextDate = dossierDate(context.modified_at || context.generated_at);
  const materialDate = dossierDate(progress.source_status?.freshness_reference_date);
  const source = recordedStage ? `项目认知记录 · 更新 ${contextDate}` : `材料自动汇总 · 资料日期 ${materialDate}`;
  intelligenceEls.progress.innerHTML = `
    <div class="progress-stage"><span>${recordedStage ? '记录中的当前阶段' : '资料推断阶段'}</span><strong>${escapeHtml(stage)}</strong></div>
    <div class="dossier-field-source">${escapeHtml(source)}；请结合实际工作核对，不代表验收结果。</div>
    ${recordedStage && inferredStage && recordedStage !== inferredStage ? `<div class="dossier-stage-note">材料自动汇总推断为“${escapeHtml(inferredStage)}”（资料日期 ${escapeHtml(materialDate)}），与认知记录不同，尚待核对。</div>` : ''}
    ${context.current_work?.length ? `<div class="progress-section"><strong>认知记录中的当前工作</strong><div class="dossier-field-source">更新 ${escapeHtml(contextDate)}；不代表正在执行的任务状态。</div>${progressItems(context.current_work, '')}</div>` : ''}
    <div class="progress-section"><strong>资料摘录：已完成</strong>${progressItems(progress.completed, '尚未从已采集资料中提取到已完成事项，不代表项目没有成果。', progress.completed_evidence || [])}</div>
    <div class="progress-section"><strong>资料摘录：进行中</strong>${progressItems(progress.in_progress, '尚未识别到明确的进行中任务，不代表无人开展工作。', progress.in_progress_evidence || [])}</div>
    ${context.known_issues?.length ? `<div class="progress-section"><strong>认知记录中的已知问题</strong><div class="dossier-field-source">更新 ${escapeHtml(contextDate)}</div>${progressItems(context.known_issues, '')}</div>` : ''}
    <div class="progress-section"><strong>资料摘录：待处理问题</strong>${progressItems(progress.issues, '已采集资料尚未提取到问题，不能据此判断项目没有问题。', progress.issue_evidence || [])}</div>
    <div class="progress-section"><strong>资料摘录：下一步</strong>${progressItems(progress.next_steps, '尚未从资料中识别下一步', progress.next_step_evidence || [])}</div>`;
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
    if (repository.role === 'materials' || String(repository.url || '').startsWith('file:')) {
      return `<div class="repository-item"><div><strong>本地资料来源</strong><div class="intelligence-list-path">${escapeHtml(repository.url || '')}</div></div><div class="repository-meta"><span>未绑定 Git 仓库</span><span>仅登记资料目录，不表示存在分支、提交或上游同步</span></div></div>`;
    }
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
  intelligenceEls.searchStatus.textContent = `找到 ${payload.count || 0} 项。${contentHint}${payload.inventory_index_file_count ? ` 另有 ${payload.inventory_index_file_count} 页文件名索引，仅登记目录元数据。` : ''}`;
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
        <span>${escapeHtml(material.metadata_only ? '目录登记（未读取正文）' : material.material_type_label || '其他资料')}</span>
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
  const requestId = ++intelligenceState.searchId;
  const isCurrent = () => intelligenceState.searchId === requestId && intelligenceState.projectId === projectId && state.selectedProjectId === projectId;
  intelligenceEls.searchButton.disabled = true;
  intelligenceEls.searchButton.textContent = '搜索中...';
  try {
    const params = new URLSearchParams({ q: query, limit: '50' });
    if (intelligenceEls.searchType.value) params.set('material_type', intelligenceEls.searchType.value);
    if (intelligenceEls.currentOnly.checked) params.set('current_only', 'true');
    const payload = await api(`/api/v1/projects/${encodeURIComponent(projectId)}/search?${params.toString()}`);
    if (isCurrent()) renderSearchResults(payload);
  } catch (error) {
    if (!isCurrent()) return;
    intelligenceEls.searchStatus.textContent = `搜索失败：${error.message}`;
    intelligenceEls.searchResults.innerHTML = '';
  } finally {
    if (!isCurrent()) return;
    intelligenceEls.searchButton.disabled = false;
    intelligenceEls.searchButton.textContent = '搜索';
  }
}

async function loadProjectIntelligence(projectId) {
  const requestId = ++intelligenceState.loadId;
  if (intelligenceState.projectId !== projectId) intelligenceEls.searchInput.value = '';
  ++intelligenceState.searchId;
  intelligenceState.projectId = projectId;
  intelligenceState.data = null;
  intelligenceState.search = null;
  intelligenceEls.searchButton.disabled = true;
  intelligenceEls.searchButton.textContent = '搜索';
  intelligenceEls.searchResults.innerHTML = '';
  intelligenceEls.searchStatus.textContent = '正在读取项目材料索引…';
  for (const key of ['summary', 'context', 'progress', 'repositories', 'categories', 'series', 'changes', 'health']) {
    intelligenceEls[key].innerHTML = '<div class="intelligence-empty">正在读取…</div>';
  }
  const project = state.projects.find(item => item.project_id === projectId) || {};
  intelligenceEls.title.textContent = `${projectLabel(project)} · 项目认知`;
  intelligenceEls.subtitle.textContent = '理解项目材料、版本关系、最近变化，并直接搜索文件内容中的关键信息';
  intelligenceEls.status.textContent = '加载中';
  intelligenceEls.status.className = 'badge neutral';
  intelligenceEls.dossier.innerHTML = '<div class="intelligence-empty">正在读取项目依据…</div>';
  let data;
  const isCurrent = () => intelligenceState.loadId === requestId && intelligenceState.projectId === projectId && state.selectedProjectId === projectId;
  try {
    data = await api(`/api/v1/projects/${encodeURIComponent(projectId)}/intelligence`);
  } catch (error) {
    if (!isCurrent()) return;
    for (const key of ['summary', 'dossier', 'context', 'progress', 'repositories', 'categories', 'series', 'changes', 'health']) {
      intelligenceEls[key].innerHTML = '<div class="intelligence-empty">读取失败，请返回项目后重试。</div>';
    }
    intelligenceEls.searchStatus.textContent = '项目概况暂不可用，仍可尝试关键词搜索。';
    intelligenceEls.searchButton.disabled = false;
    throw error;
  }
  if (!isCurrent()) return;
  intelligenceEls.searchButton.disabled = false;
  intelligenceState.data = data;
  renderDossier(data);
  renderIntelligenceSummary(data);
  renderProgress(data);
  renderRepositories(data);
  renderMaterialCategories(data);
  renderSeries(data);
  renderRecentChanges(data);
  renderHealth(data);
  const contextAvailable = data.context?.available;
  intelligenceEls.status.textContent = contextAvailable ? '项目认知已接入' : '项目背景资料待补充';
  intelligenceEls.status.className = `badge ${contextAvailable ? 'good' : 'warn'}`;
  intelligenceEls.searchStatus.textContent = (data.summary?.search_indexed_file_count || 0)
    ? `已索引 ${data.summary.search_indexed_file_count} 份材料正文。输入关键词可定位到页、Sheet/行、段落或文本行。`
    : '输入关键词可先搜索文件名、路径、用途和摘要。';
  intelligenceEls.searchResults.innerHTML = '';
}

intelligenceEls.open?.addEventListener('click', showIntelligenceView);
intelligenceEls.back?.addEventListener('click', hideIntelligenceView);
intelligenceEls.dossierSettings?.addEventListener('click', () => showSettings(intelligenceState.projectId));
intelligenceEls.dossier?.addEventListener('click', async event => {
  const button = event.target.closest?.('[data-dossier-copy]');
  if (!button) return;
  try {
    await navigator.clipboard.writeText(button.dataset.dossierCopy || '');
    showToast('材料路径已复制');
  } catch (_error) {
    showToast('浏览器未允许复制，请手动复制路径', true);
  }
});
intelligenceEls.searchButton?.addEventListener('click', runIntelligenceSearch);
intelligenceEls.searchInput?.addEventListener('keydown', event => {
  if (event.key === 'Enter') runIntelligenceSearch();
});

document.addEventListener('click', event => {
  if (event.target.closest?.('[data-project-id]')) {
    intelligenceEls.view?.classList.add('hidden');
  }
});
