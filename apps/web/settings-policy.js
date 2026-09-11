const policyEls = {
  project: document.getElementById('policy-project-select'),
  enabled: document.getElementById('policy-enabled'),
  mode: document.getElementById('policy-security-mode'),
  analysis: document.getElementById('policy-analysis-enabled'),
  llm: document.getElementById('policy-use-llm'),
  includeDocuments: document.getElementById('policy-include-documents'),
  includeTests: document.getElementById('policy-include-tests'),
  includeOutputs: document.getElementById('policy-include-outputs'),
  save: document.getElementById('policy-save-btn'),
  message: document.getElementById('policy-message'),
};

function policyProjectName(projectId) {
  return (settingsState.projects || []).find(item => item.project_id === projectId)?.project_name || projectId;
}

function renderPolicyProjectOptions(preferred = '') {
  if (!policyEls.project) return;
  const current = preferred || policyEls.project.value;
  policyEls.project.innerHTML = (settingsState.projects || []).map(project => (
    `<option value="${settingsEscape(project.project_id)}">${settingsEscape(project.project_name || project.project_id)}</option>`
  )).join('') || '<option value="">暂无业务项目</option>';
  if ((settingsState.projects || []).some(item => item.project_id === current)) policyEls.project.value = current;
}

function selectedInclude() {
  const include = [];
  if (policyEls.includeDocuments?.checked) include.push('documents');
  if (policyEls.includeTests?.checked) include.push('tests');
  if (policyEls.includeOutputs?.checked) include.push('outputs');
  return include.length ? include : ['documents', 'tests', 'outputs'];
}

function applyPolicyControls(setting) {
  const value = setting || {
    enabled: true,
    security_mode: 'metadata_only',
    analysis_enabled: false,
    use_llm: false,
    include: ['documents', 'tests', 'outputs'],
  };
  policyEls.enabled.checked = Boolean(value.enabled);
  policyEls.mode.value = value.security_mode || 'metadata_only';
  policyEls.analysis.checked = Boolean(value.analysis_enabled);
  policyEls.llm.checked = Boolean(value.use_llm);
  const include = new Set(value.include || []);
  policyEls.includeDocuments.checked = include.has('documents');
  policyEls.includeTests.checked = include.has('tests');
  policyEls.includeOutputs.checked = include.has('outputs');
  syncPolicyControlState();
}

function syncPolicyControlState() {
  const metadataOnly = policyEls.mode.value === 'metadata_only';
  if (metadataOnly) {
    policyEls.analysis.checked = false;
    policyEls.llm.checked = false;
  }
  policyEls.analysis.disabled = metadataOnly;
  policyEls.llm.disabled = metadataOnly || !policyEls.analysis.checked;
  if (policyEls.llm.disabled) policyEls.llm.checked = false;
}

function currentPolicyProjectId() {
  return policyEls.project?.value || '';
}

function loadSelectedPolicy() {
  const projectId = currentPolicyProjectId();
  if (!projectId) return;
  applyPolicyControls(settingsState.projectSettings?.[projectId]);
  setInlineMessage(policyEls.message, '');
}

async function syncPolicyToLocal(projectId, policy) {
  if (!settingsState.localOnline) return { synced: false, reason: 'local-offline' };
  const localProject = settingsState.localBindings.projects?.[projectId] || {};
  const folders = localProject.folders || [];
  const projectName = policyProjectName(projectId);
  const response = await localApi(`/api/v1/local/projects/${encodeURIComponent(projectId)}/bindings`, {
    method: 'PUT',
    body: JSON.stringify({ project_name: projectName, folders, policy }),
  });
  settingsState.localBindings.projects ||= {};
  settingsState.localBindings.projects[projectId] = {
    project_name: response.project_name || projectName,
    folders: response.folders || folders,
    policy: response.policy || policy,
  };
  return { synced: true };
}

async function saveProjectPolicy() {
  const projectId = currentPolicyProjectId();
  if (!projectId) return;
  const policy = {
    enabled: policyEls.enabled.checked,
    security_mode: policyEls.mode.value,
    analysis_enabled: policyEls.analysis.checked,
    use_llm: policyEls.llm.checked,
    include: selectedInclude(),
  };
  setBusy(policyEls.save, true, '保存中...');
  setInlineMessage(policyEls.message, '');
  try {
    const saved = await settingsApi(`/api/v1/platform/projects/${encodeURIComponent(projectId)}/settings`, {
      method: 'PUT',
      body: JSON.stringify(policy),
    });
    settingsState.projectSettings[projectId] = saved;
    let localNote = '；本机服务未连接，策略将在本机服务连接后同步';
    try {
      const result = await syncPolicyToLocal(projectId, saved);
      if (result.synced) localNote = '；本机采集策略已同步';
    } catch (error) {
      localNote = `；中央已保存，但本机同步失败：${error.message}`;
    }
    renderBusinessProjectCatalog();
    setInlineMessage(policyEls.message, `项目“${policyProjectName(projectId)}”采集策略已保存${localNote}。`);
  } catch (error) {
    setInlineMessage(policyEls.message, `保存失败：${error.message}`, true);
  } finally {
    setBusy(policyEls.save, false);
  }
}

const loadSettingsBeforePolicy = loadSettings;
loadSettings = async function loadSettingsWithPolicy() {
  await loadSettingsBeforePolicy();
  renderPolicyProjectOptions(currentPolicyProjectId() || settingsEls.localProject?.value || '');
  loadSelectedPolicy();
};

document.addEventListener('project-settings-updated', event => {
  const detail = event.detail || {};
  if (detail.projectId && detail.settings) settingsState.projectSettings[detail.projectId] = detail.settings;
  if (detail.projectId === currentPolicyProjectId()) applyPolicyControls(detail.settings);
});
policyEls.project?.addEventListener('change', loadSelectedPolicy);
policyEls.mode?.addEventListener('change', syncPolicyControlState);
policyEls.analysis?.addEventListener('change', syncPolicyControlState);
policyEls.save?.addEventListener('click', saveProjectPolicy);
