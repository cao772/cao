const state = {
  projects: [],
  selectedProjectId: null,
  detail: null,
};

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
    els.projectList.innerHTML = '<div class="empty">暂无已上报项目</div>';
    return;
  }
  els.projectList.innerHTML = state.projects.map(project => {
    const active = project.project_id === state.selectedProjectId ? ' active' : '';
    const stateLabel = project.project_state_label || '暂无状态';
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
  const current = detail.current || {};
  const fusion = current.evidence_fusion || {};
  const summary = fusion.summary || {};
  const rollup = current.project_rollup || {};
  const stateLabel = fusion.project_state_label || project.project_state_label || '暂无活动';

  els.overview.innerHTML = [
    metric('项目状态', stateLabel, fusion.formal_completion_supported ? '已启用远端证据闭环' : '当前以本地证据为主', true),
    metric('开发人员', rollup.contributor_count ?? project.contributor_count ?? 0, `${rollup.workspace_count ?? project.workspace_count ?? 0} 个工作区`),
    metric('任务事项', (detail.tasks.work_items || []).length, `${summary.completed_work_item_count || 0} 项正式完成`),
    metric('本地未提交', rollup.dirty_workspace_count ?? project.dirty_workspace_count ?? 0, '涉及的工作区'),
    metric('远端事件', project.remote_event_count ?? (detail.remoteEvents || []).length, 'Push / MR / CI / Deployment'),
  ].join('');
}

function renderTasks(detail) {
  const tasks = detail.tasks || {};
  const items = tasks.work_items || [];
  els.taskScope.textContent = tasks.formal_completion_supported ? '证据闭环' : '本地证据';
  els.taskScope.className = `badge ${tasks.formal_completion_supported ? 'good' : 'warn'}`;

  if (!items.length) {
    els.taskTable.innerHTML = '<div class="empty">尚未形成可关联的任务事项。Agent 可通过 MCP report_task_started 上报明确任务。</div>';
    return;
  }

  els.taskTable.innerHTML = `
    <table>
      <thead><tr><th>任务</th><th>当前状态</th><th>参与人员</th><th>证据说明</th></tr></thead>
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
  return `<div class="memory-tags">${items.slice(0, 12).map(item => {
    const text = typeof item === 'string' ? item : (item.text || item.title || item.content || JSON.stringify(item));
    return `<span class="memory-tag${blocker ? ' blocker' : ''}">${escapeHtml(text)}</span>`;
  }).join('')}</div>`;
}

function renderMemory(detail) {
  const memory = detail.current?.current_project_memory || {};
  els.projectMemory.innerHTML = `
    <div class="memory-row"><div class="memory-label">当前阶段</div><div class="memory-value">${escapeHtml(memory.current_stage || '尚未识别')}</div></div>
    <div class="memory-row"><div class="memory-label">进行中</div>${memoryTags(memory.in_progress)}</div>
    <div class="memory-row"><div class="memory-label">阻塞</div>${memoryTags(memory.blockers, true)}</div>
    <div class="memory-row"><div class="memory-label">下一步</div>${memoryTags(memory.next_steps)}</div>`;
}

function renderContributors(detail) {
  const data = detail.contributors || {};
  const contributors = data.contributors || [];
  if (!contributors.length) {
    els.contributors.innerHTML = '<div class="empty">暂无开发人员数据</div>';
    return;
  }
  els.contributors.innerHTML = contributors.map(item => {
    const agents = (item.agents || []).map(agent => typeof agent === 'string' ? agent : (agent.name || agent.agent_name)).filter(Boolean);
    const branches = Object.keys(item.branches || {});
    return `
      <div class="contributor">
        <div class="contributor-head"><span>${escapeHtml(item.user_id || item.name || '未知用户')}</span><span>${item.workspace_count || 0} 工作区</span></div>
        <div class="contributor-meta">
          ${agents.length ? `<span class="badge info">${escapeHtml(agents.join(' / '))}</span>` : '<span class="badge neutral">无 Agent 记录</span>'}
          ${branches.length ? `<span>${escapeHtml(branches.join(' / '))}</span>` : ''}
          ${item.dirty_workspace_count ? `<span class="badge warn">${item.dirty_workspace_count} 未提交</span>` : ''}
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

function buildTimeline(detail) {
  const items = [];
  for (const event of detail.agentEvents || []) {
    const agent = event.agent || {};
    const summary = event.data?.summary || event.data?.blocker || event.task_title || event.event_type;
    items.push({
      time: event.observed_at,
      type: 'agent',
      title: `${event.user_id || '开发人员'} / ${agent.name || 'Agent'} · ${event.event_type}`,
      detail: `${event.task_title || ''}${event.task_title && summary !== event.task_title ? ' ｜ ' : ''}${summary || ''}`,
    });
  }
  for (const event of detail.remoteEvents || []) {
    const title = event.task_title || event.data?.title || event.data?.ref || event.event_type;
    const extras = [event.repository_id, event.branch, event.commit_sha ? String(event.commit_sha).slice(0, 10) : null].filter(Boolean).join(' · ');
    items.push({
      time: event.observed_at,
      type: 'remote',
      title: `${event.provider || 'remote'} · ${event.event_type} · ${title}`,
      detail: extras,
    });
  }
  for (const snap of detail.snapshots || []) {
    const git = snap.payload?.git || {};
    const repositories = git.repositories || [];
    const dirty = repositories.length ? repositories.filter(repo => repo.dirty).length : (git.dirty ? 1 : 0);
    const branches = repositories.length ? repositories.map(repo => repo.branch).filter(Boolean) : [git.branch].filter(Boolean);
    items.push({
      time: snap.observed_at,
      type: 'local',
      title: `${snap.user_id || '开发人员'} · 本地工作区快照`,
      detail: `${snap.workspace_name || ''}${branches.length ? ` ｜ ${branches.join(' / ')}` : ''}${dirty ? ` ｜ ${dirty} 个仓库有未提交修改` : ''}`,
    });
  }
  return items.sort((a, b) => new Date(b.time || 0) - new Date(a.time || 0)).slice(0, 80);
}

function renderTimeline(detail) {
  const items = buildTimeline(detail);
  els.timelineCount.textContent = `${items.length} 条`;
  if (!items.length) {
    els.timeline.innerHTML = '<div class="empty">暂无活动记录</div>';
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
  const [current, tasks, contributors, agentEvents, remoteEvents, snapshots] = await Promise.all([
    api(`/api/v1/projects/${encoded}/current`),
    api(`/api/v1/projects/${encoded}/tasks`),
    api(`/api/v1/projects/${encoded}/contributors`),
    api(`/api/v1/projects/${encoded}/agent-events?limit=100`),
    api(`/api/v1/projects/${encoded}/remote-events?limit=200`),
    api(`/api/v1/projects/${encoded}/snapshots?limit=30`),
  ]);
  return { current, tasks, contributors, agentEvents, remoteEvents, snapshots };
}

async function selectProject(projectId) {
  state.selectedProjectId = projectId;
  renderProjectList();
  const project = state.projects.find(item => item.project_id === projectId) || {};
  els.title.textContent = projectLabel(project);
  els.subtitle.textContent = '正在加载项目事实与证据...';
  try {
    state.detail = await loadProject(projectId);
    els.subtitle.textContent = '本地开发 + Coding Agent + GitLab/GitHub 统一证据视图';
    renderOverview(project, state.detail);
    renderTasks(state.detail);
    renderMemory(state.detail);
    renderContributors(state.detail);
    renderTimeline(state.detail);
  } catch (error) {
    showToast(`加载项目失败：${error.message}`, true);
    els.subtitle.textContent = '项目数据加载失败';
  }
}

async function bootstrap() {
  try {
    await api('/health');
    els.apiState.className = 'health-dot ok';
    els.apiStateText.textContent = '中央服务正常';
    state.projects = await api('/api/v1/projects');
    renderProjectList();
    if (state.projects.length) {
      const preferred = state.selectedProjectId && state.projects.some(item => item.project_id === state.selectedProjectId)
        ? state.selectedProjectId
        : state.projects[0].project_id;
      await selectProject(preferred);
    } else {
      els.overview.innerHTML = metric('项目状态', '暂无项目', '等待本地 Sentinel 首次上报', true);
      els.taskTable.innerHTML = '<div class="empty">暂无任务数据</div>';
      els.projectMemory.innerHTML = '<div class="empty">暂无 Project Memory</div>';
      els.contributors.innerHTML = '<div class="empty">暂无人员数据</div>';
      els.timeline.innerHTML = '<div class="empty">暂无活动记录</div>';
    }
  } catch (error) {
    els.apiState.className = 'health-dot error';
    els.apiStateText.textContent = '中央服务不可用';
    showToast(`连接中央服务失败：${error.message}`, true);
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
