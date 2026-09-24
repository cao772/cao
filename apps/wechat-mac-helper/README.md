# Personal WeChat Project Collector (Mac)

M7 V1 宿主机助手。它必须运行在 macOS 宿主机，而不是 Docker 中，因为微信界面读取需要 macOS Accessibility 权限。

## 已实现

- 只允许显式配置的微信群绑定到业务项目。
- 默认本机时区每天 09:00–20:00，每 30 分钟一个采集槽，包含 20:00。
- 增量消息指纹与本机去重状态。
- 规则优先抽取：需求、决定、变更、任务、问题/阻塞、时间节点、确认。
- 向中央 /api/v1/conversation-events 上传结构化消息。
- GET /health 检查微信运行状态和 Accessibility 基础可用性。
- GET/PUT /api/v1/wechat/config 管理授权群和计划。
- POST /api/v1/wechat/scan 手工触发。
- GET /api/v1/wechat/accessibility-snapshot 手动读取前台微信控件树用于校准；默认 include_text=false，不返回 name/value 文本字段。

## 安全边界

V1 不会自动键入群名、点击搜索结果或操作发送框。未经目标 Mac 的真实控件树校准就做 UI 导航，存在把文本输入聊天编辑框的风险。

因此当前分支先完成调度、授权、增量、中央存储和检索闭环，并提供微信/Accessibility 探测。首次在目标 Mac 上调用只读校准接口，确认控件角色后再启用群聊自动读取适配器。校准接口不会点击、聚焦、输入、滚动或修改微信状态。

## 启动

在 Mac 宿主机 Python 环境中启动：

    PYTHONPATH=apps/wechat-mac-helper \
    CENTRAL_URL=http://127.0.0.1:8080 \
    COLLECTOR_TOKEN=... \
    python -m uvicorn wechat_helper:app --host 127.0.0.1 --port 6412

默认状态目录：

    ~/Library/Application Support/AI Dev Management

不要监听 0.0.0.0。


## 常驻运行

先在终端手工启动一次，确认微信与辅助功能授权正常，再安装登录常驻：

    export CENTRAL_URL=http://127.0.0.1:8080
    export COLLECTOR_TOKEN='与中央服务一致的 token'
    export USER_ID='你的平台用户标识'
    python3 apps/wechat-mac-helper/install_macos.py

安装后使用 macOS LaunchAgent 常驻；助手自己按本机时区执行 09:00、09:30 ... 19:30、20:00 的采集槽。

卸载常驻服务但保留本地配置与去重状态：

    python3 apps/wechat-mac-helper/uninstall_macos.py

注意：LaunchAgent 运行身份仍需获得 macOS Accessibility 权限。正式启用自动读取前，先通过只读校准接口确认当前微信版本的控件结构。
