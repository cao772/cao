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
            <strong>${settingsEscape(node.user_id || '未知人员')}</strong>
            <span>${settingsEscape(node.device_id || '未知设备')}</span>
          </div>
          <div class="collector-node-projects">${projectTags}</div>
        </div>
        <div class="collector-node-meta">
          <span class="badge ${nodeStatusTone(node.status)}">${settingsEscape(nodeStatusLabel(node.status))}</span>
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
