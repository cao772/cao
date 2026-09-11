const businessProjectEls = {
  count: document.getElementById('business-project-count'),
  id: document.getElementById('business-project-id'),
  name: document.getElementById('business-project-name'),
  description: document.getElementById('business-project-description'),
  create: document.getElementById('business-project-create-btn'),
  message: document.getElementById('business-project-message'),
  list: document.getElementById('business-project-list'),
};

function renderBusinessProjectCatalog() {
  const projects = settingsState.projects || [];
  businessProjectEls.count.textContent = `${projects.length} 个项目`;
  if (!projects.length) {
    businessProjectEls.list.innerHTML = '<div class="empty">尚未建立业务项目</div>';
    return;
  }
  businessProjectEls.list.innerHTML = projects.map(project => `
    <div class="selection-item project-catalog-item">
      <div class="project-catalog-main">
        <span class="project-catalog-name">${settingsEscape(project.project_name || project.project_id)}</span>
        <span class="project-catalog-id">${settingsEscape(project.project_id)}</span>
        ${project.description ? `<span class="project-catalog-desc">${settingsEscape(project.description)}</span>` : ''}
      </div>
      <div class="project-catalog-tags">
        ${project.sampled ? '<span class="badge good">已采集</span>' : '<span class="badge neutral">待采集</span>'}
        ${project.managed ? '<span class="badge info">平台配置</span>' : '<span class="badge neutral">自动识别</span>'}
      </div>
    </div>`).join('');
}

async function reloadBusinessProjects(preferredProjectId = '') {
  const payload = await settingsApi('/api/v1/platform/projects');
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
  setBusy(businessProjectEls.create, true, '创建中...');
  setInlineMessage(businessProjectEls.message, '');
  try {
    const response = await settingsApi('/api/v1/platform/projects', {
      method: 'POST',
      body: JSON.stringify({
        project_id: projectId,
        project_name: projectName,
        description: businessProjectEls.description.value.trim() || null,
      }),
    });
    businessProjectEls.id.value = '';
    businessProjectEls.name.value = '';
    businessProjectEls.description.value = '';
    await reloadBusinessProjects(response.project?.project_id || projectId);
    await loadScopedLocalFolders();
    setInlineMessage(businessProjectEls.message, `项目“${response.project?.project_name || projectName}”已创建，可继续绑定仓库和本机目录。`);
  } catch (error) {
    setInlineMessage(businessProjectEls.message, `创建失败：${error.message}`, true);
  } finally {
    setBusy(businessProjectEls.create, false);
  }
}

const loadSettingsBeforeProjectCatalog = loadSettings;
loadSettings = async function loadSettingsWithProjectCatalog() {
  settingsEls.status.textContent = '加载中';
  settingsEls.status.className = 'badge neutral';
  const [projectData, config, bindingData] = await Promise.all([
    settingsApi('/api/v1/platform/projects'),
    settingsApi('/api/v1/platform/gitlab'),
    settingsApi('/api/v1/platform/project-bindings'),
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
