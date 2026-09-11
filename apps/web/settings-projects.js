const businessProjectEls = {
  count: document.getElementById('business-project-count'),
  id: document.getElementById('business-project-id'),
  name: document.getElementById('business-project-name'),
  description: document.getElementById('business-project-description'),
  create: document.getElementById('business-project-create-btn'),
  cancel: document.getElementById('business-project-cancel-btn'),
  message: document.getElementById('business-project-message'),
  list: document.getElementById('business-project-list'),
};

settingsState.projectSettings ||= {};
let editingBusinessProjectId = '';

function projectRuntimeSetting(projectId) {
  return settingsState.projectSettings?.[projectId] || {
    enabled: true,
    security_mode: 'metadata_only',
    analysis_enabled: false,
    use_llm: false,
    include: ['documents', 'tests', 'outputs'],
  };
}

function resetBusinessProjectEditor() {
  editingBusinessProjectId = '';
  businessProjectEls.id.readOnly = false;
  businessProjectEls.id.value = '';
  businessProjectEls.name.value = '';
  businessProjectEls.description.value = '';
  businessProjectEls.create.textContent = '创建业务项目';
  businessProjectEls.cancel?.classList.add('hidden');
}

function renderBusinessProjectCatalog() {
  const projects = settingsState.projects || [];
  businessProjectEls.count.textContent = `${projects.length} 个项目`;
  if (!projects.length) {
    businessProjectEls.list.innerHTML = '<div class="empty">尚未建立业务项目</div>';
    return;
  }
  businessProjectEls.list.innerHTML = projects.map(project => {
    const setting = projectRuntimeSetting(project.project_id);
    return `
    <div class="selection-item project-catalog-item ${setting.enabled ? '' : 'project-disabled'}">
      <div class="project-catalog-main">
        <span class="project-catalog-name">${settingsEscape(project.project_name || project.project_id)}</span>
        <span class="project-catalog-id">${settingsEscape(project.project_id)}</span>
        ${project.description ? `<span class="project-catalog-desc">${settingsEscape(project.description)}</span>` : ''}
      </div>
      <div class="project-catalog-side">
        <div class="project-catalog-tags">
          ${setting.enabled ? '<span class="badge good">采集中</span>' : '<span class="badge warn">已停用</span>'}
          ${project.sampled ? '<span class="badge good">已采集</span>' : '<span class="badge neutral">待采集</span>'}
          ${project.managed ? '<span class="badge info">平台配置</span>' : '<span class="badge neutral">自动识别</span>'}
        </div>
        <div class="project-catalog-actions">
          ${project.managed ? `<button class="text-button project-edit-btn" type="button" data-project-id="${settingsEscape(project.project_id)}">编辑</button>` : ''}
          <button class="text-button project-toggle-btn" type="button" data-project-id="${settingsEscape(project.project_id)}">${setting.enabled ? '停用' : '启用'}</button>
        </div>
      </div>
    </div>`;
  }).join('');
}

async function loadProjectSettingsMap() {
  const payload = await settingsApi('/api/v1/platform/project-settings');
  settingsState.projectSettings = payload.settings || {};
  return settingsState.projectSettings;
}

async function reloadBusinessProjects(preferredProjectId = '') {
  const [payload] = await Promise.all([
    settingsApi('/api/v1/platform/projects'),
    loadProjectSettingsMap(),
  ]);
  settingsState.projects = payload.projects || [];
  renderBusinessProjects();
  renderBusinessProjectCatalog();
  if (preferredProjectId) {
    if (settingsState.projects.some(project => project.project_id === preferredProjectId)) {
      settingsEls.bindingProject.value = preferredProjectId;
      settingsEls.localProject.value = preferredProjectId;
      renderGitLabProjects();
    }
  }
  return payload;
}

async function createBusinessProject() {
  const projectId = businessProjectEls.id.value.trim();
  const projectName = businessProjectEls.name.value.trim();
  if (!projectId || !projectName) {
    setInlineMessage(businessProjectEls.message, '请填写项目标识和项目名称。', true);
    return;
  }
  const editing = Boolean(editingBusinessProjectId);
  setBusy(businessProjectEls.create, true, editing ? '保存中...' : '创建中...');
  setInlineMessage(businessProjectEls.message, '');
  try {
    const response = await settingsApi(
      editing ? `/api/v1/platform/projects/${encodeURIComponent(editingBusinessProjectId)}` : '/api/v1/platform/projects',
      {
        method: editing ? 'PUT' : 'POST',
        body: JSON.stringify(editing ? {
          project_name: projectName,
          description: businessProjectEls.description.value.trim() || null,
        } : {
          project_id: projectId,
          project_name: projectName,
          description: businessProjectEls.description.value.trim() || null,
        }),
      },
    );
    const savedId = response.project?.project_id || projectId;
    resetBusinessProjectEditor();
    await reloadBusinessProjects(savedId);
    if (typeof loadScopedLocalFolders === 'function') await loadScopedLocalFolders();
    setInlineMessage(businessProjectEls.message, editing
      ? `项目“${response.project?.project_name || projectName}”已更新。`
      : `项目“${response.project?.project_name || projectName}”已创建，可继续绑定仓库和本机目录。`);
  } catch (error) {
    setInlineMessage(businessProjectEls.message, `${editing ? '保存' : '创建'}失败：${error.message}`, true);
  } finally {
    setBusy(businessProjectEls.create, false);
    businessProjectEls.create.textContent = editingBusinessProjectId ? '保存修改' : '创建业务项目';
  }
}

function beginEditBusinessProject(projectId) {
  const project = (settingsState.projects || []).find(item => item.project_id === projectId);
  if (!project?.managed) return;
  editingBusinessProjectId = projectId;
  businessProjectEls.id.value = projectId;
  businessProjectEls.id.readOnly = true;
  businessProjectEls.name.value = project.project_name || '';
  businessProjectEls.description.value = project.description || '';
  businessProjectEls.create.textContent = '保存修改';
  businessProjectEls.cancel?.classList.remove('hidden');
  businessProjectEls.name.focus();
}

async function toggleBusinessProject(projectId) {
  const current = projectRuntimeSetting(projectId);
  const next = { ...current, enabled: !current.enabled };
  try {
    const saved = await settingsApi(`/api/v1/platform/projects/${encodeURIComponent(projectId)}/settings`, {
      method: 'PUT',
      body: JSON.stringify(next),
    });
    settingsState.projectSettings[projectId] = saved;
    renderBusinessProjectCatalog();
    setInlineMessage(businessProjectEls.message, `${saved.enabled ? '已启用' : '已停用'}项目 ${projectId}。`);
    document.dispatchEvent(new CustomEvent('project-settings-updated', { detail: { projectId, settings: saved } }));
  } catch (error) {
    setInlineMessage(businessProjectEls.message, `状态更新失败：${error.message}`, true);
  }
}

loadSettings = async function loadSettingsWithProjectCatalog() {
  settingsEls.status.textContent = '加载中';
  settingsEls.status.className = 'badge neutral';
  const [projectData, config, bindingData] = await Promise.all([
    settingsApi('/api/v1/platform/projects'),
    settingsApi('/api/v1/platform/gitlab'),
    settingsApi('/api/v1/platform/project-bindings'),
    loadProjectSettingsMap(),
  ]);
  settingsState.projects = projectData.projects || [];
  settingsState.bindings = bindingData.bindings || [];
  renderBusinessProjects();
  renderBusinessProjectCatalog();
  renderGitLabConnection(config);
  renderGitLabProjects();
  await loadLocalControl();
  settingsEls.status.textContent = '配置已加载';
  settingsEls.status.className = 'badge good';
};

businessProjectEls.create?.addEventListener('click', createBusinessProject);
businessProjectEls.cancel?.addEventListener('click', resetBusinessProjectEditor);
businessProjectEls.list?.addEventListener('click', event => {
  const edit = event.target.closest?.('.project-edit-btn');
  if (edit) beginEditBusinessProject(edit.dataset.projectId);
  const toggle = event.target.closest?.('.project-toggle-btn');
  if (toggle) toggleBusinessProject(toggle.dataset.projectId);
});
