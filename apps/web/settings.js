const settingsState = {
  projects: [],
  gitlabProjects: [],
  bindings: [],
  localBindings: { version: 1, projects: {} },
  folderTree: [],
  localOnline: false,
};

const settingsEls = {
  nav: document.getElementById('settings-nav'),
  dashboard: document.getElementById('dashboard-view'),
  view: document.getElementById('settings-view'),
  status: document.getElementById('settings-status'),
  gitlabState: document.getElementById('gitlab-connection-state'),
  gitlabBaseUrl: document.getElementById('gitlab-base-url'),
  gitlabToken: document.getElementById('gitlab-token'),
  gitlabTokenHint: document.getElementById('gitlab-token-hint'),
  gitlabTest: document.getElementById('gitlab-test-btn'),
  gitlabSave: document.getElementById('gitlab-save-btn'),
  gitlabDiscover: document.getElementById('gitlab-discover-btn'),
  gitlabMessage: document.getElementById('gitlab-message'),
  gitlabProjectCount: document.getElementById('gitlab-project-count'),
  gitlabProjectSearch: document.getElementById('gitlab-project-search'),
  gitlabProjectTable: document.getElementById('gitlab-project-table'),
  bindingProject: document.getElementById('binding-project-select'),
  bindingSave: document.getElementById('binding-save-btn'),
  localState: document.getElementById('local-control-state'),
  localInfo: document.getElementById('local-info'),
  localProject: document.getElementById('local-project-select'),
  localRefresh: document.getElementById('local-refresh-btn'),
  localFolderTree: document.getElementById('local-folder-tree'),
  localSelection: document.getElementById('local-selection'),
  localSave: document.getElementById('local-save-btn'),
  localScan: document.getElementById('local-scan-btn'),
  localMessage: document.getElementById('local-message'),
};

const LOCAL_CONTROL = 'http://127.0.0.1:6411';
const ROLE_LABELS = {
  code: '代码',
  documents: '项目资料',
  tests: '测试',
  outputs: '输出',
};

function settingsEscape(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

async function settingsApi(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `${response.status} ${response.statusText}`);
  return data;
}

async function localApi(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch(`${LOCAL_CONTROL}${path}`, {
      ...options,
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...(options.headers || {}),
      },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `${response.status} ${response.statusText}`);
    return data;
  } finally {
    clearTimeout(timer);
  }
}

function setInlineMessage(element, message = '', error = false) {
  element.textContent = message;
  element.className = `inline-message${message ? ' visible' : ''}${error ? ' error' : ''}`;
}

function setBusy(button, busy, busyText = '处理中...') {
  if (!button) return;
  if (busy) {
    button.dataset.originalText = button.textContent;
    button.textContent = busyText;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.originalText || button.textContent;
    button.disabled = false;
  }
}

function showSettings() {
  settingsEls.dashboard.classList.add('hidden');
  settingsEls.view.classList.remove('hidden');
  settingsEls.nav.classList.add('active');
  document.querySelectorAll('.project-item[data-project-id]').forEach(item => item.classList.remove('active'));
  loadSettings().catch(error => {
    settingsEls.status.textContent = '加载失败';
    settingsEls.status.className = 'badge bad';
    setInlineMessage(settingsEls.gitlabMessage, `配置加载失败：${error.message}`, true);
  });
}

function showDashboard() {
  settingsEls.view.classList.add('hidden');
  settingsEls.dashboard.classList.remove('hidden');
  settingsEls.nav.classList.remove('active');
}

function renderBusinessProjects() {
  const options = settingsState.projects.map(project => (
    `<option value="${settingsEscape(project.project_id)}">${settingsEscape(project.project_name || project.project_id)}</option>`
  )).join('');
  const currentBinding = settingsEls.bindingProject.value;
  const currentLocal = settingsEls.localProject.value;
  settingsEls.bindingProject.innerHTML = options || '<option value="">暂无业务项目</option>';
  settingsEls.localProject.innerHTML = options || '<option value="">暂无业务项目</option>';
  if (settingsState.projects.some(project => project.project_id === currentBinding)) settingsEls.bindingProject.value = currentBinding;
  if (settingsState.projects.some(project => project.project_id === currentLocal)) settingsEls.localProject.value = currentLocal;
}

function renderGitLabConnection(config) {
  settingsEls.gitlabBaseUrl.value = config.base_url || 'http://git.hyetec.com';
  settingsEls.gitlabToken.value = '';
  settingsEls.gitlabTokenHint.textContent = config.configured
    ? `已配置 ${config.token_hint || ''}，页面不会回显完整 Token`
    : '尚未配置 Token';
  const account = config.account?.username ? ` · ${config.account.username}` : '';
  settingsEls.gitlabState.textContent = config.configured ? `已配置${account}` : '未配置';
  settingsEls.gitlabState.className = `connection-state ${config.configured ? 'ok' : ''}`;
}

function bindingMap() {
  return new Map(settingsState.bindings.map(item => [String(item.repository_id), item.project_id]));
}

function selectedBindingProject() {
  return settingsEls.bindingProject.value;
}

function renderGitLabProjects() {
  const search = settingsEls.gitlabProjectSearch.value.trim().toLowerCase();
  const selectedProject = selectedBindingProject();
  const bindings = bindingMap();
  const rows = settingsState.gitlabProjects.filter(item => {
    if (!search) return true;
    return `${item.name || ''} ${item.path_with_namespace || ''}`.toLowerCase().includes(search);
  });
  settingsEls.gitlabProjectCount.textContent = `${settingsState.gitlabProjects.length} 个项目`;
  if (!rows.length) {
    settingsEls.gitlabProjectTable.innerHTML = '<div class="empty">没有匹配的 GitLab 项目</div>';
    return;
  }
  settingsEls.gitlabProjectTable.innerHTML = `
    <table class="repo-table">
      <thead><tr><th class="check-col"></th><th>项目</th><th>路径</th><th>默认分支</th><th>最近活动</th><th>当前绑定</th></tr></thead>
      <tbody>${rows.map(item => {
        const id = String(item.id || '');
        const bound = bindings.get(id) || item.bound_project_id || '';
        const boundElsewhere = bound && bound !== selectedProject;
        const checked = bound === selectedProject ? ' checked' : '';
        const disabled = boundElsewhere ? ' disabled' : '';
        const date = item.last_activity_at ? new Date(item.last_activity_at).toLocaleDateString('zh-CN') : '-';
        const boundName = settingsState.projects.find(project => project.project_id === bound)?.project_name || bound || '-';
        return `<tr>
          <td><input class="repo-check" type="checkbox" data-repo-id="${settingsEscape(id)}"${checked}${disabled}></td>
          <td><strong>${settingsEscape(item.name || '-')}</strong></td>
          <td><span class="path-text">${settingsEscape(item.path_with_namespace || '-')}</span></td>
          <td>${settingsEscape(item.default_branch || '-')}</td>
          <td>${settingsEscape(date)}</td>
          <td>${boundElsewhere ? `<span class="badge warn">${settingsEscape(boundName)}</span>` : (bound ? `<span class="badge good">${settingsEscape(boundName)}</span>` : '<span class="muted">未绑定</span>')}</td>
        </tr>`;
      }).join('')}</tbody>
    </table>`;
}

async function discoverGitLab() {
  setBusy(settingsEls.gitlabDiscover, true, '检索中...');
  setInlineMessage(settingsEls.gitlabMessage, '');
  try {
    const data = await settingsApi('/api/v1/platform/gitlab/discover', {
      method: 'POST',
      body: JSON.stringify({ search: null }),
    });
    settingsState.gitlabProjects = data.projects || [];
    const bindingData = await settingsApi('/api/v1/platform/project-bindings');
    settingsState.bindings = bindingData.bindings || [];
    renderGitLabProjects();
    setInlineMessage(settingsEls.gitlabMessage, `已检索到 ${data.count || 0} 个可访问项目。`);
  } catch (error) {
    setInlineMessage(settingsEls.gitlabMessage, `检索失败：${error.message}`, true);
  } finally {
    setBusy(settingsEls.gitlabDiscover, false);
  }
}

async function testGitLab() {
  setBusy(settingsEls.gitlabTest, true, '测试中...');
  setInlineMessage(settingsEls.gitlabMessage, '');
  try {
    const data = await settingsApi('/api/v1/platform/gitlab/test', {
      method: 'POST',
      body: JSON.stringify({
        base_url: settingsEls.gitlabBaseUrl.value.trim(),
        token: settingsEls.gitlabToken.value || null,
      }),
    });
    const who = data.account?.name || data.account?.username || '当前账号';
    setInlineMessage(settingsEls.gitlabMessage, `连接成功：${who}`);
    settingsEls.gitlabState.textContent = '连接正常';
    settingsEls.gitlabState.className = 'connection-state ok';
  } catch (error) {
    settingsEls.gitlabState.textContent = '连接失败';
    settingsEls.gitlabState.className = 'connection-state error';
    setInlineMessage(settingsEls.gitlabMessage, `连接失败：${error.message}`, true);
  } finally {
    setBusy(settingsEls.gitlabTest, false);
  }
}

async function saveGitLab() {
  setBusy(settingsEls.gitlabSave, true, '保存中...');
  setInlineMessage(settingsEls.gitlabMessage, '');
  try {
    const payload = {
      base_url: settingsEls.gitlabBaseUrl.value.trim(),
      token: settingsEls.gitlabToken.value || null,
    };
    const config = await settingsApi('/api/v1/platform/gitlab', {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
    renderGitLabConnection(config);
    await discoverGitLab();
  } catch (error) {
    setInlineMessage(settingsEls.gitlabMessage, `保存失败：${error.message}`, true);
  } finally {
    setBusy(settingsEls.gitlabSave, false);
  }
}

async function saveRepositoryBindings() {
  const projectId = selectedBindingProject();
  if (!projectId) return;
  const selectedIds = new Set(
    [...settingsEls.gitlabProjectTable.querySelectorAll('.repo-check:checked')].map(input => input.dataset.repoId)
  );
  const repositories = settingsState.gitlabProjects.filter(item => selectedIds.has(String(item.id))).map(item => ({
    repository_id: String(item.id),
    name: item.name || item.path_with_namespace,
    path_with_namespace: item.path_with_namespace,
    web_url: item.web_url,
    default_branch: item.default_branch,
    visibility: item.visibility,
    last_activity_at: item.last_activity_at,
  }));
  setBusy(settingsEls.bindingSave, true, '保存中...');
  try {
    await settingsApi(`/api/v1/platform/projects/${encodeURIComponent(projectId)}/repositories`, {
      method: 'PUT',
      body: JSON.stringify({ repositories }),
    });
    const bindingData = await settingsApi('/api/v1/platform/project-bindings');
    settingsState.bindings = bindingData.bindings || [];
    renderGitLabProjects();
    setInlineMessage(settingsEls.gitlabMessage, `已保存 ${repositories.length} 个仓库到当前业务项目。`);
  } catch (error) {
    setInlineMessage(settingsEls.gitlabMessage, `仓库绑定失败：${error.message}`, true);
  } finally {
    setBusy(settingsEls.bindingSave, false);
  }
}

function flattenFolders(nodes, depth = 0, result = []) {
  for (const node of nodes || []) {
    result.push({ ...node, depth });
    flattenFolders(node.children || [], depth + 1, result);
  }
  return result;
}

function currentLocalFolders() {
  const projectId = settingsEls.localProject.value;
  return settingsState.localBindings.projects?.[projectId]?.folders || [];
}

function renderLocalTree() {
  const flat = flattenFolders(settingsState.folderTree);
  const current = new Map(currentLocalFolders().map(item => [item.path, item.role]));
  if (!flat.length) {
    settingsEls.localFolderTree.innerHTML = '<div class="empty">当前授权根目录下没有可选文件夹</div>';
    renderLocalSelection();
    return;
  }
  settingsEls.localFolderTree.innerHTML = flat.map(item => {
    const role = current.get(item.path) || 'documents';
    const checked = current.has(item.path) ? ' checked' : '';
    return `<div class="folder-row" style="--folder-depth:${item.depth}">
      <label><input class="folder-check" type="checkbox" data-folder="${settingsEscape(item.path)}"${checked}><span class="folder-name">${settingsEscape(item.name)}</span><span class="folder-path">${settingsEscape(item.path)}</span></label>
      <select class="folder-role" data-folder-role="${settingsEscape(item.path)}"${checked ? '' : ' disabled'}>
        ${Object.entries(ROLE_LABELS).map(([value, label]) => `<option value="${value}"${role === value ? ' selected' : ''}>${label}</option>`).join('')}
      </select>
    </div>`;
  }).join('');
  settingsEls.localFolderTree.querySelectorAll('.folder-check').forEach(input => {
    input.addEventListener('change', () => {
      const role = settingsEls.localFolderTree.querySelector(`[data-folder-role="${CSS.escape(input.dataset.folder)}"]`);
      if (role) role.disabled = !input.checked;
      renderLocalSelection();
    });
  });
  settingsEls.localFolderTree.querySelectorAll('.folder-role').forEach(select => {
    select.addEventListener('change', renderLocalSelection);
  });
  renderLocalSelection();
}

function readLocalSelectionFromDom() {
  return [...settingsEls.localFolderTree.querySelectorAll('.folder-check:checked')].map(input => {
    const role = settingsEls.localFolderTree.querySelector(`[data-folder-role="${CSS.escape(input.dataset.folder)}"]`);
    return { path: input.dataset.folder, role: role?.value || 'documents' };
  });
}

function renderLocalSelection() {
  const folders = readLocalSelectionFromDom();
  if (!folders.length) {
    settingsEls.localSelection.innerHTML = '<div class="empty">尚未选择目录</div>';
    return;
  }
  settingsEls.localSelection.innerHTML = folders.map(item => `
    <div class="selection-item"><span>${settingsEscape(item.path)}</span><strong>${settingsEscape(ROLE_LABELS[item.role] || item.role)}</strong></div>
  `).join('');
}

async function loadLocalControl() {
  try {
    const [health, info, folders, bindings] = await Promise.all([
      localApi('/health'),
      localApi('/api/v1/local/info'),
      localApi('/api/v1/local/folders?depth=4'),
      localApi('/api/v1/local/bindings'),
    ]);
    settingsState.localOnline = health.status === 'ok';
    settingsState.folderTree = folders.folders || [];
    settingsState.localBindings = bindings || { version: 1, projects: {} };
    settingsEls.localState.textContent = '本机服务正常';
    settingsEls.localState.className = 'connection-state ok';
    settingsEls.localInfo.innerHTML = `
      <span><b>${settingsEscape(info.user_id || '-')}</b> · ${settingsEscape(info.device_id || '-')}</span>
      <span>授权根目录 <b>${settingsEscape(info.projects_root || '/projects')}</b></span>`;
    renderLocalTree();
    setInlineMessage(settingsEls.localMessage, '');
  } catch (error) {
    settingsState.localOnline = false;
    settingsEls.localState.textContent = '本机服务未连接';
    settingsEls.localState.className = 'connection-state error';
    settingsEls.localInfo.innerHTML = '';
    settingsEls.localFolderTree.innerHTML = '<div class="empty">无法读取本机目录。请确认 Local Control 已在 127.0.0.1:6411 启动。</div>';
    setInlineMessage(settingsEls.localMessage, `本机服务：${error.name === 'AbortError' ? '连接超时' : error.message}`, true);
  }
}

async function saveLocalBindings() {
  const projectId = settingsEls.localProject.value;
  if (!projectId || !settingsState.localOnline) return;
  const folders = readLocalSelectionFromDom();
  setBusy(settingsEls.localSave, true, '保存中...');
  try {
    const data = await localApi(`/api/v1/local/projects/${encodeURIComponent(projectId)}/bindings`, {
      method: 'PUT',
      body: JSON.stringify({ folders }),
    });
    settingsState.localBindings.projects ||= {};
    settingsState.localBindings.projects[projectId] = { folders: data.folders || folders };
    renderLocalTree();
    setInlineMessage(settingsEls.localMessage, `已保存 ${folders.length} 个本机采集目录。`);
  } catch (error) {
    setInlineMessage(settingsEls.localMessage, `保存失败：${error.message}`, true);
  } finally {
    setBusy(settingsEls.localSave, false);
  }
}

async function scanLocalProject() {
  const projectId = settingsEls.localProject.value;
  if (!projectId || !settingsState.localOnline) return;
  setBusy(settingsEls.localScan, true, '采集中...');
  try {
    const result = await localApi(`/api/v1/local/projects/${encodeURIComponent(projectId)}/scan`, { method: 'POST' });
    setInlineMessage(settingsEls.localMessage, result.uploaded
      ? `采集完成，已上传 ${result.uploaded} 个新快照。返回项目页刷新即可查看。`
      : '采集已执行，但没有成功上传新快照。',
      !result.uploaded);
  } catch (error) {
    setInlineMessage(settingsEls.localMessage, `采集失败：${error.message}`, true);
  } finally {
    setBusy(settingsEls.localScan, false);
  }
}

async function loadSettings() {
  settingsEls.status.textContent = '加载中';
  settingsEls.status.className = 'badge neutral';
  const [projects, config, bindingData] = await Promise.all([
    settingsApi('/api/v1/projects'),
    settingsApi('/api/v1/platform/gitlab'),
    settingsApi('/api/v1/platform/project-bindings'),
  ]);
  settingsState.projects = projects || [];
  settingsState.bindings = bindingData.bindings || [];
  renderBusinessProjects();
  renderGitLabConnection(config);
  renderGitLabProjects();
  await loadLocalControl();
  settingsEls.status.textContent = '配置已加载';
  settingsEls.status.className = 'badge good';
}

settingsEls.nav?.addEventListener('click', showSettings);
document.addEventListener('click', event => {
  if (event.target.closest?.('[data-project-id]')) showDashboard();
});
settingsEls.gitlabTest?.addEventListener('click', testGitLab);
settingsEls.gitlabSave?.addEventListener('click', saveGitLab);
settingsEls.gitlabDiscover?.addEventListener('click', discoverGitLab);
settingsEls.gitlabProjectSearch?.addEventListener('input', renderGitLabProjects);
settingsEls.bindingProject?.addEventListener('change', renderGitLabProjects);
settingsEls.bindingSave?.addEventListener('click', saveRepositoryBindings);
settingsEls.localRefresh?.addEventListener('click', loadLocalControl);
settingsEls.localProject?.addEventListener('change', renderLocalTree);
settingsEls.localSave?.addEventListener('click', saveLocalBindings);
settingsEls.localScan?.addEventListener('click', scanLocalProject);
