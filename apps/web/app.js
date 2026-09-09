const state = { projects: [], selectedProjectId: null, detail: null };

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
  const rollup = detail.current?.project_rollup || {};
  const issueCount = (brief.issues || []).length;
  els.overview.innerHTML = [
    metric('当前阶段', brief.current_stage || '尚未识别', '根据当前项目资料与开发进展归纳', true),
    metric('开发人员', rollup.contributor_count ?? project.contributor_count ?? 0, `${rollup.workspace_count ?? project.workspace_count ?? 0} 个工作区`),
    metric('进行中任务', summary.in_progress_task_count ?? 0, `${summary.planned_task_count ?? 0} 项待开始`),
    metric('待处理问题', issueCount, issueCount ? '需要继续跟进' : '当前未识别到明确问题'),
    metric('本周提交', summary.weekly_commit_count ?? 0, `${summary.weekly_merge_count ?? 0} 次代码合并`),
  ].join('');
}

function renderTasks(detail) {
  const tasks = detail.tasks || {};
  const items = tasks.work_items || [];
  const activeCount = items.filter(item => !['completed', 'planned'].includes(String(item.status || ''))).length;
  els.taskScope.textContent = items.length ? `${activeCount} 项进行中` : '暂无任务';
  els.taskScope.className = `badge ${activeCount ? 'info' : 'neutral'}`;
  if (!items.length) {
    els.taskTable.innerHTML = '<div class="empty">尚未识别到明确任务，可从需求、工作任务表和开发活动中继续形成任务。</div>';
    return;
  }
  els.taskTable.innerHTML = `
    <table>
      <thead><tr><th>任务</th><th>当前状态</th><th>参与人员</th><th>进展说明</th></tr></thead>
      <tbody>
        ${items.map(item => {
          const contributors = (item.contributors || []).join('、') || '-';
          const reasons = (item.status_reasons || []).slice(0, 4);
          return `<tr>
            <td><div class="task-title">${escapeHtml(item.title || item.task_id || '未命名事项')}</div><div class="muted">${escapeHtml(item.task_id || '')}</div></td>
            <td><span class="badge ${statusTone(item.status)}">${escapeHtml(item.status_label || item.status || '未知')}</span></td>
            <td>${escapeHtml(contributors)}</td>
            <td><div class="reason-list">${reasons.length ? reasons.map(escapeHtml).join('<br>') : '-'}</div></td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>`;
}

function memoryTags(items, blocker = false) {
  if (!items || !items.length) return '<span class="muted">暂无</span>';
  return `<div class="memory-tags">${items.slice(0, 10).map(item => {
    const text = typeof item === 'string' ? item : (item.text || item.title || item.content || JSON.stringify(item));
    return `<span class="memory-tag${blocker ? ' blocker' : ''}">${escapeHtml(text)}</span>`;
  }).join('')}</div>`;
}

function renderMemory(detail) {
  const brief = detail.brief || {};
  els.projectMemory.innerHTML = `
    <div class="memory-row"><div class="memory-label">当前阶段</div><div class="memory-value">${escapeHtml(brief.current_stage || '尚未识别')}</div></div>
    <div class="memory-row"><div class="memory-label">已完成</div>${memoryTags(brief.completed)}</div>
    <div class="memory-row"><div class="memory-label">进行中</div>${memoryTags(brief.in_progress)}</div>
    <div class="memory-row"><div class="memory-label">问题</div>${memoryTags(brief.issues, true)}</div>
    <div class="memory-row"><div class="memory-label">下一步</div>${memoryTags(brief.next_steps)}</div>
    <div class="memory-row"><div class="memory-label">最新指标</div>${memoryTags(brief.latest_metrics)}</div>`;
}

function renderContributors(detail) {
  const contributors = detail.contributors?.contributors || [];
  if (!contributors.length) {
    els.contributors.innerHTML = '<div class="empty">暂无人员数据</div>';
    return;
  }
  els.contributors.innerHTML = contributors.map(item => {
    const agents = (item.agents || []).map(agent => typeof agent === 'string' ? agent : (agent.name || agent.agent_name)).filter(Boolean);
    const branches = Array.isArray(item.branches) ? item.branches : Object.keys(item.branches || {});
    return `
      <div class="contributor">
        <div class="contributor-head"><span>${escapeHtml(item.user_id || item.name || '未知用户')}</span><span>${item.workspace_count || 0} 工作区</span></div>
        <div class="contributor-meta">
          ${agents.length ? `<span class="badge info">${escapeHtml(agents.join(' / '))}</span>` : ''}
          ${branches.length ? `<span>${escapeHtml(branches.join(' / '))}</span>` : ''}
          ${item.dirty_workspace_count ? `<span class="badge warn">${item.dirty_workspace_count} 待提交</span>` : ''}
        </div>
      </div>`;
  }).join('');
}

function eventTime(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { hour12: false });
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
  const extras = [event.repository_id, event.branch].filter(Boolean).join(' · ');
  return {
    time: event.observed_at,
    type: 'remote',
    title: name ? `${label}：${name}` : label,
    detail: extras,
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
  const title = dirty ? `${snap.user_id || '开发人员'} · 本地修改待提交` : `${snap.user_id || '开发人员'} · 本地开发状态更新`;
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

  return items.sort((a, b) => new Date(b.time || 0) - new Date(a.time || 0)).slice(0, 60);
}

function renderTimeline(detail) {
  const items = buildTimeline(detail);
  els.timelineCount.textContent = `${items.length} 条`;
  if (!items.length) {
    els.timeline.innerHTML = '<div class="empty">暂无近期活动</div>';
    return;
  }
  els.timeline.innerHTML = items.map(item => `
    <div class="timeline-item">
      <div class="timeline-time">${escapeHtml(eventTime(item.time))}</div>
      <div class="timeline-dot ${item.type}"></div>
      <div><div class="timeline-title">${escapeHtml(item.title)}</div><div class="timeline-detail">${escapeHtml(item.detail || '')}</div></div>
    </div>`).join('');
}

async function loadProject(projectId) {
  const encoded = encodeURIComponent(projectId);
  const [current, brief, tasks, contributors, agentEvents, remoteEvents, snapshots] = await Promise.all([
    api(`/api/v1/projects/${encoded}/current`),
    api(`/api/v1/projects/${encoded}/brief`),
    api(`/api/v1/projects/${encoded}/tasks`),
    api(`/api/v1/projects/${encoded}/contributors`),
    api(`/api/v1/projects/${encoded}/agent-events?limit=100`),
    api(`/api/v1/projects/${encoded}/remote-events?limit=300`),
    api(`/api/v1/projects/${encoded}/snapshots?limit=80`),
  ]);
  return { current, brief, tasks, contributors, agentEvents, remoteEvents, snapshots };
}

async function selectProject(projectId) {
  state.selectedProjectId = projectId;
  renderProjectList();
  const project = state.projects.find(item => item.project_id === projectId) || {};
  els.title.textContent = projectLabel(project);
  els.subtitle.textContent = '';
  try {
    state.detail = await loadProject(projectId);
    renderOverview(project, state.detail);
    renderTasks(state.detail);
    renderMemory(state.detail);
    renderContributors(state.detail);
    renderTimeline(state.detail);
  } catch (error) {
    showToast(`加载项目失败：${error.message}`, true);
  }
}

async function bootstrap() {
  try {
    await api('/health');
    els.apiState.className = 'health-dot ok';
    els.apiStateText.textContent = '服务正常';
    state.projects = await api('/api/v1/projects');
    renderProjectList();
    if (state.projects.length) {
      const preferred = state.selectedProjectId && state.projects.some(item => item.project_id === state.selectedProjectId)
        ? state.selectedProjectId
        : state.projects[0].project_id;
      await selectProject(preferred);
    } else {
      els.overview.innerHTML = metric('项目状态', '暂无项目', '等待项目首次采集', true);
      els.taskTable.innerHTML = '<div class="empty">暂无任务数据</div>';
      els.projectMemory.innerHTML = '<div class="empty">暂无项目进展</div>';
      els.contributors.innerHTML = '<div class="empty">暂无人员数据</div>';
      els.timeline.innerHTML = '<div class="empty">暂无近期活动</div>';
    }
  } catch (error) {
    els.apiState.className = 'health-dot error';
    els.apiStateText.textContent = '服务不可用';
    showToast(`连接服务失败：${error.message}`, true);
  }
}

els.refresh.addEventListener('click', async () => {
  els.refresh.disabled = true;
  try {
    await bootstrap();
    showToast('数据已刷新');
  } finally {
    els.refresh.disabled = false;
  }
});

bootstrap();
