const localToolbar = document.querySelector('.local-toolbar');
const localFolderSearchField = document.createElement('label');
localFolderSearchField.className = 'field search-field local-folder-search-field';
localFolderSearchField.innerHTML = '<span>筛选本机目录</span><input id="local-folder-search" type="search" placeholder="输入文件夹名称或路径" autocomplete="off" />';
if (localToolbar && settingsEls.localRefresh) {
  localToolbar.insertBefore(localFolderSearchField, settingsEls.localRefresh);
}
const localFolderSearch = document.getElementById('local-folder-search');

function filterFolderTree(nodes, query) {
  const text = String(query || '').trim().toLowerCase();
  if (!text) return nodes || [];
  const visit = node => {
    const children = (node.children || []).map(visit).filter(Boolean);
    const haystack = `${node.name || ''} ${node.path || ''}`.toLowerCase();
    if (haystack.includes(text) || children.length) return { ...node, children };
    return null;
  };
  return (nodes || []).map(visit).filter(Boolean);
}

function renderScopedFolderTree() {
  settingsState.folderTree = filterFolderTree(settingsState.fullFolderTree || [], localFolderSearch?.value || '');
  renderLocalTree();
}

async function loadScopedLocalFolders() {
  const projectId = settingsEls.localProject.value;
  if (!settingsState.localOnline || !projectId) {
    settingsState.fullFolderTree = [];
    settingsState.folderTree = [];
    renderLocalTree();
    return;
  }
  settingsEls.localFolderTree.innerHTML = '<div class="empty">正在读取当前项目目录...</div>';
  try {
    const folders = await localApi(`/api/v1/local/folders?depth=5&project_id=${encodeURIComponent(projectId)}`);
    settingsState.fullFolderTree = folders.folders || [];
    renderScopedFolderTree();
    if (folders.scope === 'authorized-root') {
      setInlineMessage(settingsEls.localMessage, '该项目尚未建立本机 project.yaml，可从当前 Docker 已授权目录中选择多个文件夹。');
    } else {
      setInlineMessage(settingsEls.localMessage, '');
    }
  } catch (error) {
    settingsState.fullFolderTree = [];
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

settingsEls.localProject?.addEventListener('change', () => {
  if (localFolderSearch) localFolderSearch.value = '';
  loadScopedLocalFolders();
});
localFolderSearch?.addEventListener('input', renderScopedFolderTree);
