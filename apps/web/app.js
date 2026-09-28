const state = { projects: [], selectedProjectId: null, detail: null, portfolioRows: [], portfolioLoadId: 0 };

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
};

async function api(path) {
  const response = await fetch(path, { headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
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

function renderPortfolio() {
  const rows = state.portfolioRows;
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
  const filtered = rows.filter(row => {
    const brief = row.brief || {};
    const knowledge = row.intelligence || {};
    return [projectLabel(row.project), knowledge.profile?.description, knowledge.context?.project?.purpose,
      knowledge.context?.project?.current_stage, brief.current_stage, ...(brief.next_steps || [])]
      .some(value => String(value || '').toLocaleLowerCase().includes(query));
  });
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
  }).join('') : `<div class="portfolio-empty">${query ? '没有匹配的项目。请试试项目名称或背景关键词。' : '暂无项目，等待首次采集。'}</div>`;
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
  els.portfolioGrid.innerHTML = '<div class="portfolio-empty">正在读取项目概况…</div>';
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
  state.selectedProjectId = null;
  renderProjectList();
  els.portfolioNav.classList.add('active');
  document.getElementById('settings-nav')?.classList.remove('active');
  document.getElementById('settings-view')?.classList.add('hidden');
  document.getElementById('intelligence-view')?.classList.add('hidden');
  document.getElementById('dashboard-view')?.classList.add('hidden');
  els.portfolioView.classList.remove('hidden');
  return loadPortfolio().catch(error => {
    els.portfolioStatus.textContent = '项目概况读取失败';
    els.portfolioGrid.innerHTML = '<div class="portfolio-empty">读取失败，请点击“刷新数据”重试。</div>';
    showToast(`读取项目总览失败：${error.message}`, true);
  });
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
  if (index === 0) return `本周 · ${range}`;
  if (index === 1) return `上周 · ${range}`;
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
  const [current, brief, tasks, contributors, agentEvents, remoteEvents, snapshots] = await Promise.all([
    api(`/api/v1/projects/${encoded}/current`),
    api(`/api/v1/projects/${encoded}/brief`),
    api(`/api/v1/projects/${encoded}/tasks`),
    api(`/api/v1/projects/${encoded}/contributors`),
    api(`/api/v1/projects/${encoded}/agent-events?limit=100`),
    api(`/api/v1/projects/${encoded}/remote-events?limit=500`),
    api(`/api/v1/projects/${encoded}/snapshots?limit=120`),
  ]);
  return { current, brief, tasks, contributors, agentEvents, remoteEvents, snapshots };
}

async function selectProject(projectId) {
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
    if (state.selectedProjectId !== projectId) return;
    state.detail = detail;
    renderOverview(project, state.detail);
    renderTasks(state.detail);
    renderMemory(state.detail);
    renderContributors(state.detail);
    renderTimeline(state.detail);
  } catch (error) {
    if (state.selectedProjectId !== projectId) return;
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
els.portfolioRefresh.addEventListener('click', async () => {
  els.portfolioRefresh.disabled = true;
  try {
    if (await bootstrap()) showToast('数据已刷新');
  } finally {
    els.portfolioRefresh.disabled = false;
  }
});

bootstrap();
