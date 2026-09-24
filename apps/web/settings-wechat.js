const WECHAT_HELPER_BASE = "http://127.0.0.1:6412";

function wechatEscape(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, function(char) {
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char];
  });
}

async function wechatApi(path, options) {
  options = options || {};
  const controller = new AbortController();
  const timer = setTimeout(function() { controller.abort(); }, 5000);
  try {
    const response = await fetch(WECHAT_HELPER_BASE + path, Object.assign({}, options, {
      headers: Object.assign({"Content-Type":"application/json"}, options.headers || {}),
      signal: controller.signal
    }));
    const payload = await response.json().catch(function() { return {}; });
    if (!response.ok) throw new Error(payload.detail || "微信助手请求失败");
    return payload;
  } finally {
    clearTimeout(timer);
  }
}

function ensureWeChatSettingsCard() {
  if (document.getElementById("wechat-helper-state")) return;
  const stack = document.querySelector(".settings-stack");
  if (!stack) return;

  const style = document.createElement("style");
  style.id = "wechat-settings-styles";
  style.textContent =
    ".wechat-schedule-strip{display:flex;gap:8px;flex-wrap:wrap;margin:0 20px 14px}" +
    ".wechat-binding-form{display:grid;grid-template-columns:220px minmax(260px,1fr) auto;gap:10px;align-items:end;margin:0 20px}" +
    ".wechat-binding-list{margin:14px 20px 0;border:1px solid #dfe7ef;border-radius:8px;overflow:hidden}" +
    ".wechat-binding-item{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:center;padding:11px 13px;border-bottom:1px solid #e8eef4;background:#fff}" +
    ".wechat-binding-item:last-child{border-bottom:0}.wechat-binding-main strong{color:#294e6b;font-size:12px}" +
    ".wechat-binding-main div{margin-top:3px;color:#8192a3;font-size:10px}.wechat-remove{border:0;background:transparent;color:#9b5555;cursor:pointer;font-size:11px}" +
    ".wechat-note{margin:10px 20px 0;color:#7f90a1;font-size:10px;line-height:1.6}@media(max-width:980px){.wechat-binding-form{grid-template-columns:1fr}}";
  document.head.appendChild(style);

  const card = document.createElement("div");
  card.className = "panel settings-card";
  card.innerHTML =
    '<div class="settings-card-head"><div><h3>个人微信接入</h3><p>仅采集你明确绑定到业务项目的微信群；其他群和私聊不进入平台。</p></div>' +
    '<div id="wechat-helper-state" class="connection-state">正在检测宿主机助手</div></div>' +
    '<div class="wechat-schedule-strip"><span class="badge info">每天 09:00–20:00</span><span class="badge info">每 30 分钟</span>' +
    '<label class="policy-toggle"><input id="wechat-enabled" type="checkbox" checked /><span>启用定时采集</span></label></div>' +
    '<div class="wechat-binding-form"><label class="field"><span>业务项目</span><select id="wechat-project-select"></select></label>' +
    '<label class="field"><span>微信群名称</span><input id="wechat-group-name" type="text" placeholder="填写微信中显示的完整群名" autocomplete="off" /></label>' +
    '<button id="wechat-add-btn" class="secondary-button align-bottom" type="button">添加绑定</button></div>' +
    '<div id="wechat-binding-list" class="wechat-binding-list"><div class="empty">尚未绑定微信群</div></div>' +
    '<div class="wechat-note">宿主机助手只监听 127.0.0.1:6412。当前安全模式不会自动键入或点击微信；首次需在目标 Mac 校准只读 Accessibility 控件树后才启用自动读取。</div>' +
    '<div class="settings-actions right-actions"><button id="wechat-refresh-btn" class="secondary-button" type="button">刷新状态</button>' +
    '<button id="wechat-scan-btn" class="secondary-button" type="button">立即检查</button><button id="wechat-save-btn" class="primary-button" type="button">保存微信群绑定</button></div>' +
    '<div id="wechat-message" class="inline-message"></div>';

  const localCard = Array.from(stack.children).find(function(item) { return item.querySelector && item.querySelector("#local-control-state"); });
  if (localCard && localCard.nextSibling) stack.insertBefore(card, localCard.nextSibling);
  else stack.appendChild(card);
}

ensureWeChatSettingsCard();

const wechatEls = {
  state: document.getElementById("wechat-helper-state"),
  enabled: document.getElementById("wechat-enabled"),
  project: document.getElementById("wechat-project-select"),
  group: document.getElementById("wechat-group-name"),
  add: document.getElementById("wechat-add-btn"),
  list: document.getElementById("wechat-binding-list"),
  refresh: document.getElementById("wechat-refresh-btn"),
  scan: document.getElementById("wechat-scan-btn"),
  save: document.getElementById("wechat-save-btn"),
  message: document.getElementById("wechat-message")
};

let wechatConfig = {version:1,enabled:true,start_time:"09:00",end_time:"20:00",interval_minutes:30,bindings:[]};

function renderWeChatProjects() {
  const projects = settingsState.projects || [];
  wechatEls.project.innerHTML = projects.map(function(item) {
    return '<option value="' + wechatEscape(item.project_id) + '">' + wechatEscape(item.project_name || item.project_id) + "</option>";
  }).join("");
}

function renderWeChatBindings() {
  const bindings = wechatConfig.bindings || [];
  if (!bindings.length) {
    wechatEls.list.innerHTML = '<div class="empty">尚未绑定微信群。未绑定的群不会采集。</div>';
    return;
  }
  wechatEls.list.innerHTML = bindings.map(function(item, index) {
    return '<div class="wechat-binding-item"><div class="wechat-binding-main"><strong>' + wechatEscape(item.group_name) +
      "</strong><div>关联项目：" + wechatEscape(item.project_name || item.project_id) +
      '</div></div><button class="wechat-remove" type="button" data-wechat-remove="' + index + '">移除</button></div>';
  }).join("");
  wechatEls.list.querySelectorAll("[data-wechat-remove]").forEach(function(button) {
    button.addEventListener("click", function() {
      wechatConfig.bindings.splice(Number(button.dataset.wechatRemove), 1);
      renderWeChatBindings();
    });
  });
}

function setWeChatMessage(text, error) {
  wechatEls.message.textContent = text || "";
  wechatEls.message.classList.toggle("error", Boolean(error));
}

async function loadWeChatConfig(showMessage) {
  renderWeChatProjects();
  try {
    const values = await Promise.all([wechatApi("/health"), wechatApi("/api/v1/wechat/config")]);
    const health = values[0], config = values[1];
    wechatConfig = Object.assign({}, wechatConfig, config, {bindings:config.bindings || []});
    wechatEls.enabled.checked = wechatConfig.enabled !== false;
    renderWeChatBindings();
    const available = Boolean(health.wechat && health.wechat.available);
    const captureMode = health.wechat && health.wechat.capture_mode;
    const captureReady = available && Boolean(captureMode) && captureMode !== "safe_adapter_required";
    wechatEls.state.textContent = captureReady ? "微信采集就绪" : (available ? "微信运行中，采集待校准" : "助手在线，微信待授权");
    wechatEls.state.className = "connection-state " + (captureReady ? "ok" : (available ? "" : "error"));
    if (showMessage) {
      setWeChatMessage(captureReady ? "宿主机助手正常，定时计划与群绑定已加载。" : (available ? "群绑定已保存；当前版本仍需校准微信控件，尚未自动读取或上传消息。" : "宿主机助手已启动：" + ((health.wechat && health.wechat.reason) || "微信暂不可读取")), !available);
    }
  } catch (error) {
    wechatEls.state.textContent = "宿主机助手未连接";
    wechatEls.state.className = "connection-state error";
    if (showMessage) setWeChatMessage("请先在 Mac 宿主机启动微信助手（127.0.0.1:6412）。", true);
  }
}

wechatEls.add.addEventListener("click", function() {
  const projectId = wechatEls.project.value;
  const groupName = wechatEls.group.value.trim();
  const project = (settingsState.projects || []).find(function(item) { return item.project_id === projectId; });
  if (!projectId || !groupName) return setWeChatMessage("请选择业务项目并填写完整微信群名称。", true);
  if ((wechatConfig.bindings || []).some(function(item) { return item.project_id === projectId && item.group_name === groupName; })) {
    return setWeChatMessage("这个微信群已经绑定到该项目。", true);
  }
  wechatConfig.bindings.push({project_id:projectId,project_name:(project && project.project_name) || projectId,group_name:groupName});
  wechatEls.group.value = "";
  renderWeChatBindings();
  setWeChatMessage("已加入待保存列表。");
});

wechatEls.save.addEventListener("click", async function() {
  setBusy(wechatEls.save, true, "保存中...");
  try {
    wechatConfig = await wechatApi("/api/v1/wechat/config", {
      method:"PUT",
      body:JSON.stringify({enabled:wechatEls.enabled.checked,start_time:"09:00",end_time:"20:00",interval_minutes:30,bindings:wechatConfig.bindings || []})
    });
    renderWeChatBindings();
    setWeChatMessage("已保存 " + wechatConfig.bindings.length + " 个微信群绑定。未绑定群不会采集。");
  } catch (error) {
    setWeChatMessage("保存失败：" + error.message, true);
  } finally {
    setBusy(wechatEls.save, false);
  }
});

wechatEls.refresh.addEventListener("click", function() { loadWeChatConfig(true); });
wechatEls.scan.addEventListener("click", async function() {
  setBusy(wechatEls.scan, true, "检查中...");
  try {
    const result = await wechatApi("/api/v1/wechat/scan", {method:"POST"});
    if (result.requires_calibration) setWeChatMessage("微信与辅助功能已可访问，但仍需在这台 Mac 上校准只读群聊控件树后才能自动采集。");
    else setWeChatMessage((result.wechat && result.wechat.reason) || "本次检查完成。", !(result.wechat && result.wechat.available));
  } catch (error) {
    setWeChatMessage("检查失败：" + error.message, true);
  } finally {
    setBusy(wechatEls.scan, false);
  }
});

const loadSettingsBeforeWeChat = loadSettings;
loadSettings = async function loadSettingsWithWeChat() {
  await loadSettingsBeforeWeChat();
  await loadWeChatConfig(false);
};
