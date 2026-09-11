async function loadScopedLocalFolders() {
  const projectId = settingsEls.localProject.value;
  if (!settingsState.localOnline || !projectId) {
    settingsState.folderTree = [];
    renderLocalTree();
    return;
  }
  settingsEls.localFolderTree.innerHTML = '<div class="empty">正在读取当前项目目录...</div>';
  try {
    const folders = await localApi(`/api/v1/local/folders?depth=4&project_id=${encodeURIComponent(projectId)}`);
    settingsState.folderTree = folders.folders || [];
    renderLocalTree();
  } catch (error) {
    settingsState.folderTree = [];
    settingsEls.localFolderTree.innerHTML = '<div class="empty">当前业务项目在这台电脑上没有可配置目录。</div>';
    setInlineMessage(settingsEls.localMessage, `目录读取失败：${error.message}`, true);
  }
}

const originalLoadSettings = loadSettings;
loadSettings = async function loadSettingsWithScopedFolders() {
  await originalLoadSettings();
  await loadScopedLocalFolders();
};

settingsEls.localProject?.addEventListener('change', loadScopedLocalFolders);
