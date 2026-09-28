const modelEls = {
  state: document.getElementById('model-connection-state'),
  baseUrl: document.getElementById('model-base-url'),
  model: document.getElementById('model-name'),
  apiKey: document.getElementById('model-api-key'),
  apiKeyHint: document.getElementById('model-api-key-hint'),
  allowRemote: document.getElementById('model-allow-remote'),
  timeout: document.getElementById('model-timeout'),
  test: document.getElementById('model-test-btn'),
  save: document.getElementById('model-save-btn'),
  message: document.getElementById('model-message'),
};

function renderModelConfig(config) {
  modelEls.baseUrl.value = config.base_url || '';
  modelEls.model.value = config.model || '';
  modelEls.apiKey.value = '';
  modelEls.apiKeyHint.textContent = config.configured
    ? `已配置 ${config.api_key_hint || ''}，页面不会回显完整密钥`
    : '尚未配置模型密钥';
  modelEls.allowRemote.checked = config.allow_remote_endpoint !== false;
  modelEls.timeout.value = config.timeout_seconds || 60;
  modelEls.state.textContent = config.configured ? '已配置' : '未配置';
  modelEls.state.className = `connection-state ${config.configured ? 'ok' : ''}`;
}

function modelPayload() {
  return {
    base_url: modelEls.baseUrl.value.trim(),
    model: modelEls.model.value.trim(),
    api_key: modelEls.apiKey.value || null,
    allow_remote_endpoint: modelEls.allowRemote.checked,
    timeout_seconds: Number(modelEls.timeout.value || 60),
  };
}

async function loadModelConfig() {
  try {
    const config = await settingsApi('/api/v1/platform/model');
    renderModelConfig(config);
  } catch (error) {
    modelEls.state.textContent = '加载失败';
    modelEls.state.className = 'connection-state error';
    setInlineMessage(modelEls.message, `模型配置加载失败：${error.message}`, true);
  }
}

async function testModelConfig() {
  const payload = modelPayload();
  if (!payload.base_url || !payload.model) {
    setInlineMessage(modelEls.message, '请填写模型接口地址和模型名称。', true);
    return;
  }
  setBusy(modelEls.test, true, '测试中...');
  setInlineMessage(modelEls.message, '');
  try {
    const result = await settingsApi('/api/v1/platform/model/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    modelEls.state.textContent = '连接正常';
    modelEls.state.className = 'connection-state ok';
    setInlineMessage(modelEls.message, `连接成功：${result.response_model || result.model || payload.model}`);
  } catch (error) {
    modelEls.state.textContent = '连接失败';
    modelEls.state.className = 'connection-state error';
    setInlineMessage(modelEls.message, `连接失败：${error.message}`, true);
  } finally {
    setBusy(modelEls.test, false);
  }
}

async function saveModelConfig() {
  const payload = modelPayload();
  if (!payload.base_url || !payload.model) {
    setInlineMessage(modelEls.message, '请填写模型接口地址和模型名称。', true);
    return;
  }
  setBusy(modelEls.save, true, '保存中...');
  setInlineMessage(modelEls.message, '');
  try {
    const config = await settingsApi('/api/v1/platform/model', {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
    renderModelConfig(config);
    setInlineMessage(modelEls.message, '模型配置已保存。项目是否启用模型分析仍由上方“采集策略”单独控制。');
  } catch (error) {
    setInlineMessage(modelEls.message, `保存失败：${error.message}`, true);
  } finally {
    setBusy(modelEls.save, false);
  }
}

const loadSettingsBeforeModel = loadSettings;
loadSettings = async function loadSettingsWithModel() {
  await loadSettingsBeforeModel();
  await loadModelConfig();
};

modelEls.test?.addEventListener('click', testModelConfig);
modelEls.save?.addEventListener('click', saveModelConfig);
