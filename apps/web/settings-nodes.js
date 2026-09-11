function ensureCollectorNodeStyles() {
  if (document.getElementById('collector-node-styles')) return;
  const style = document.createElement('style');
  style.id = 'collector-node-styles';
  style.textContent = `
    .collector-node-head-meta { display:flex; align-items:center; gap:10px; flex-wrap:wrap; justify-content:flex-end; }
    .collector-node-summary { display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
    .collector-node-list { margin:18px 20px 0; border:1px solid #dfe7ef; border-radius:8px; overflow:hidden; background:#fbfcfe; }
    .collector-node-item { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:18px; align-items:center; padding:14px 16px; border-bottom:1px solid #e9eef3; background:#fff; }
    .collector-node-item:last-child { border-bottom:0; }
    .collector-node-main { min-width:0; display:grid; gap:8px; }
    .collector-node-title { display:flex; align-items:baseline; gap:10px; min-width:0; }
    .collector-node-title strong { color:#254a6d; font-size:13px; }
    .collector-node-title span { color:#8293a4; font-size:11px; font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .collector-node-projects { display:flex; gap:6px; flex-wrap:wrap; }
    .node-project-pill { display:inline-flex; align-items:center; max-width:260px; padding:3px 8px; border:1px solid #d5e1ec; border-radius:999px; background:#f6f9fc; color:#56718a; font-size:10px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .collector-node-meta { display:grid; justify-items:end; gap:4px; color:#7b8da0; font-size:10px; white-space:nowrap; }
    @media (max-width: 980px) { .collector-node-item { grid-template-columns:1fr; } .collector-node-meta { justify-items:start; white-space:normal; } }
  `;
  document.head.appendChild(style);
}

function ensureCollectorNodeCard() {
  if (document.getElementById('collector-node-list')) return;
  const stack = document.querySelector('.settings-stack');
  if (!stack) return;
  const card = document.createElement('div');
  card.className = 'panel settings-card';
  card.innerHTML = `
    <div class="settings-card-head">
      <div>
        <h3>采集节点</h3>
        <p>查看哪些开发人员电脑已接入、最后采集时间以及参与的项目。</p>
      </div>
      <div class="collector-node-head-meta">
        <div id="collector-node-summary" class="collector-node-summary"></div>
        <span id="collector-node-count" class="badge neutral">0 个节点</span>
      </div>
    </div>
    <div id="collector-node-list" class="collector-node-list"><div class="empty">正在读取采集节点</div></div>
    <div class="settings-actions right-actions">
      <button id="collector-node-refresh-btn" class="secondary-button" type="button">刷新节点状态</button>
    </div>
    <div id="collector-node-message" class="inline-message"></div>
  `;
  const localCard = [...stack.children].find(item => item.querySelector?.('#local-control-state'));
  if (localCard) stack.insertBefore(card, localCard);
  else stack.appendChild(card);
}

ensureCollectorNodeStyles();
ensureCollectorNodeCard();

const nodeEls = {
  count: document.getElementById('collector-node-count'),
  summary: document.getElementById('collector-node-summary'),
  list: document.getElementById('collector-node-list'),
  refresh: document.getElementById('collector-node-refresh-btn'),
  message: document.getElementById('collector-node-message'),
};

settingsState.collectorNodes ||= [];

function nodeStatusLabel(status) {
  return {
    online: '在线',
    stale: '近期未采集',
    offline: '离线',
    unknown: '未知',
  }[status] || status || '未知';
}

function nodeStatusTone(status) {
  return {
    online: 'good',
    stale: 'warn',
    offline: 'bad',
    unknown: 'neutral',
  }[status] || 'neutral';
}

function formatNodeTime(value) {
  if (!value) return '暂无采集时间';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

function renderCollectorNodes(payload) {
  const nodes = payload?.nodes || [];
  const summary = payload?.summary || {};
  settingsState.collectorNodes = nodes;
  if (nodeEls.count) nodeEls.count.textContent = `${nodes.length} 个节点`;
  if (nodeEls.summary) {
    nodeEls.summary.innerHTML = [
      `<span class="badge good">在线 ${summary.online || 0}</span>`,
      `<span class="badge warn">待确认 ${summary.stale || 0}</span>`,
      `<span class="badge bad">离线 ${summary.offline || 0}</span>`,
    ].join('');
  }
  if (!nodeEls.list) return;
  if (!nodes.length) {
    nodeEls.list.innerHTML = '<div class="empty">还没有收到开发人员电脑的采集数据。安装并启动本机 Sentinel 后会自动出现在这里。</div>';
    return;
  }
  nodeEls.list.innerHTML = nodes.map(node => {
    const projects = node.projects || [];
    const projectTags = projects.length
      ? projects.map(project => `<span class="node-project-pill" title="${settingsEscape((project.workspaces || []).join(' / '))}">${settingsEscape(project.project_name || project.project_id)}</span>`).join('')
      : '<span class="muted">暂无项目</span>';
    return `
      <div class="collector-node-item">
        <div class="collector-node-main">
          <div class="collector-node-title">
            <strong>${settingsEscape(node.display_name || node.user_id || '未知人员')}</strong>
            <span>${settingsEscape(node.device_id || '未知设备')}</span>
          </div>
          <div class="collector-node-projects">${projectTags}</div>
        </div>
        <div class="collector-node-meta">
          <span class="badge ${nodeStatusTone(node.status)}">${settingsEscape(nodeStatusLabel(node.status))}</span>
          ${node.device_identity_conflict ? '<span class="badge bad">设备身份冲突</span>' : ''}
          <span>${node.project_count || 0} 个项目 · ${node.workspace_count || 0} 个工作区</span>
          <span>最后采集 ${settingsEscape(formatNodeTime(node.last_seen_at))}</span>
        </div>
      </div>`;
  }).join('');
}

async function loadCollectorNodes(showMessage = false) {
  if (showMessage) setInlineMessage(nodeEls.message, '正在刷新采集节点...');
  try {
    const payload = await settingsApi('/api/v1/platform/nodes');
    renderCollectorNodes(payload);
    if (showMessage) setInlineMessage(nodeEls.message, `已刷新 ${payload.count || 0} 个采集节点。`);
    return payload;
  } catch (error) {
    if (nodeEls.list) nodeEls.list.innerHTML = '<div class="empty">采集节点读取失败</div>';
    setInlineMessage(nodeEls.message, `采集节点读取失败：${error.message}`, true);
    return null;
  }
}

const loadSettingsBeforeNodes = loadSettings;
loadSettings = async function loadSettingsWithNodes() {
  await loadSettingsBeforeNodes();
  await loadCollectorNodes(false);
};

nodeEls.refresh?.addEventListener('click', async () => {
  setBusy(nodeEls.refresh, true, '刷新中...');
  try {
    await loadCollectorNodes(true);
  } finally {
    setBusy(nodeEls.refresh, false);
  }
});

if (!document.getElementById('settings-view')?.classList.contains('hidden')) {
  loadCollectorNodes(false);
}

function ensurePeopleDeviceCard() {
  if (document.getElementById('people-device-list')) return;
  const stack = document.querySelector('.settings-stack');
  if (!stack) return;
  const style = document.createElement('style');
  style.id = 'people-device-styles';
  style.textContent = `
    .people-device-list { margin:18px 20px 0; border:1px solid #dfe7ef; border-radius:8px; overflow:hidden; background:#fbfcfe; }
    .people-device-item { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:18px; padding:14px 16px; border-bottom:1px solid #e9eef3; background:#fff; }
    .people-device-item:last-child { border-bottom:0; }
    .people-device-main { min-width:0; display:grid; gap:8px; }
    .people-device-title { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
    .people-device-title strong { color:#254a6d; font-size:13px; }
    .people-device-identities,.people-device-projects,.people-device-machines { display:flex; gap:6px; flex-wrap:wrap; }
    .identity-pill,.people-project-pill,.people-machine-pill { display:inline-flex; align-items:center; max-width:300px; padding:3px 8px; border:1px solid #d5e1ec; border-radius:999px; background:#f6f9fc; color:#56718a; font-size:10px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .people-device-meta { display:grid; justify-items:end; align-content:start; gap:5px; color:#7b8da0; font-size:10px; white-space:nowrap; }
    @media (max-width: 980px) { .people-device-item { grid-template-columns:1fr; } .people-device-meta { justify-items:start; white-space:normal; } }
  `;
  document.head.appendChild(style);

  const card = document.createElement('div');
  card.className = 'panel settings-card';
  card.innerHTML = `
    <div class="settings-card-head">
      <div>
        <h3>人员与设备</h3>
        <p>统一查看本机、GitLab/GitHub 与 Agent 用户身份；未确认身份不会自动并入同名人员。</p>
      </div>
      <div class="collector-node-head-meta">
        <div id="people-device-summary" class="collector-node-summary"></div>
        <span id="people-device-count" class="badge neutral">0 人</span>
      </div>
    </div>
    <div id="people-device-list" class="people-device-list"><div class="empty">正在读取人员与设备</div></div>
    <div class="settings-actions right-actions">
      <button id="people-device-refresh-btn" class="secondary-button" type="button">刷新人员与设备</button>
    </div>
    <div id="people-device-message" class="inline-message"></div>
  `;
  const collectorCard = [...stack.children].find(item => item.querySelector?.('#collector-node-list'));
  if (collectorCard) stack.insertBefore(card, collectorCard);
  else stack.appendChild(card);
}

ensurePeopleDeviceCard();

const peopleEls = {
  count: document.getElementById('people-device-count'),
  summary: document.getElementById('people-device-summary'),
  list: document.getElementById('people-device-list'),
  refresh: document.getElementById('people-device-refresh-btn'),
  message: document.getElementById('people-device-message'),
};

settingsState.people ||= [];

function renderPeopleDevices(payload) {
  const people = payload?.people || [];
  const deviceSummary = payload?.device_summary || {};
  settingsState.people = people;
  if (peopleEls.count) peopleEls.count.textContent = `${payload?.person_count || 0} 人`;
  if (peopleEls.summary) {
    peopleEls.summary.innerHTML = [
      `<span class="badge good">在线设备 ${deviceSummary.online || 0}</span>`,
      `<span class="badge bad">离线 ${deviceSummary.offline || 0}</span>`,
      `<span class="badge warn">未确认身份 ${payload?.unconfirmed_identity_count || 0}</span>`,
    ].join('');
  }
  if (!peopleEls.list) return;
  if (!people.length) {
    peopleEls.list.innerHTML = '<div class="empty">还没有人员身份数据。收到本机、仓库或 Agent 活动后会自动出现在这里。</div>';
    return;
  }

  peopleEls.list.innerHTML = people.map(person => {
    const unresolved = !person.person_id;
    const identities = (person.identities || []).map(identity => (
      `<span class="identity-pill">${settingsEscape(identity.provider || 'unknown')}: ${settingsEscape(identity.external_id || '')}</span>`
    )).join('');
    const machines = (person.devices || []).map(device => (
      `<span class="people-machine-pill">${settingsEscape(device.display_name || device.device_id || '未知设备')} · ${settingsEscape(nodeStatusLabel(device.status))}</span>`
    )).join('');
    const currentProjects = person.current_projects || [];
    const projects = currentProjects.map(project => (
      `<span class="people-project-pill">${settingsEscape(project.project_name || project.project_id)}</span>`
    )).join('');
    const possible = (person.possible_persons || []).length
      ? `<span>${person.possible_persons.length} 个可能匹配，仅供人工确认</span>`
      : '';

    return `
      <div class="people-device-item">
        <div class="people-device-main">
          <div class="people-device-title">
            <strong>${settingsEscape(person.display_name || '未命名人员')}</strong>
            ${unresolved ? '<span class="badge warn">身份未确认</span>' : ''}
            ${person.status === 'inactive' ? '<span class="badge neutral">停用</span>' : ''}
          </div>
          <div class="people-device-identities">${identities || '<span class="muted">暂无身份</span>'}</div>
          <div class="people-device-machines">${machines || '<span class="muted">暂无设备</span>'}</div>
          <div class="people-device-projects">${projects || '<span class="muted">暂无近期项目</span>'}</div>
        </div>
        <div class="people-device-meta">
          <span>${person.project_count || 0} 个参与项目</span>
          <span>${(person.devices || []).length} 台设备</span>
          <span>最近活动 ${settingsEscape(formatNodeTime(person.last_activity_at))}</span>
          ${possible}
        </div>
      </div>`;
  }).join('');
}

async function loadPeopleDevices(showMessage = false) {
  if (showMessage) setInlineMessage(peopleEls.message, '正在刷新人员与设备...');
  try {
    const payload = await settingsApi('/api/v1/platform/people');
    renderPeopleDevices(payload);
    if (showMessage) setInlineMessage(
      peopleEls.message,
      `已刷新 ${payload.person_count || 0} 人，${payload.unconfirmed_identity_count || 0} 个身份待确认。`
    );
    return payload;
  } catch (error) {
    if (peopleEls.list) peopleEls.list.innerHTML = '<div class="empty">人员与设备读取失败</div>';
    setInlineMessage(peopleEls.message, `人员与设备读取失败：${error.message}`, true);
    return null;
  }
}

const loadSettingsBeforePeople = loadSettings;
loadSettings = async function loadSettingsWithPeople() {
  await loadSettingsBeforePeople();
  await loadPeopleDevices(false);
};

peopleEls.refresh?.addEventListener('click', async () => {
  setBusy(peopleEls.refresh, true, '刷新中...');
  try {
    await loadPeopleDevices(true);
  } finally {
    setBusy(peopleEls.refresh, false);
  }
});

if (!document.getElementById('settings-view')?.classList.contains('hidden')) {
  loadPeopleDevices(false);
}
