# Personal WeChat Project Collector (Mac)

M7 宿主机助手。它通过 TraceMemo 的本地 HTTP API 增量读取明确绑定的微信群，并把项目沟通事件写入本机 Central。

## 已实现

- 只允许显式配置的微信群绑定到业务项目。
- 默认本机时区每天 09:00–20:00，每 30 分钟一个采集槽，包含 20:00。
- 增量消息指纹与本机去重状态。
- 规则优先抽取：需求、决定、变更、任务、问题/阻塞、时间节点、确认。
- 向中央 /api/v1/conversation-events 上传结构化消息。
- GET /health 检查 TraceMemo 本地数据库和 API Token 状态。
- GET/PUT /api/v1/wechat/config 管理授权群和计划。
- POST /api/v1/wechat/scan 手工触发。
- GET /api/v1/wechat/accessibility-snapshot 手动读取前台微信控件树用于校准；默认 include_text=false，不返回 name/value 文本字段。

## 接入与安全边界

先在 Mac 上运行已连接微信本地数据库的 TraceMemo，并启用其 Local API。将 Bearer Token 存入 `~/Library/Application Support/AI Dev Management/tracememo-api-token`，文件权限设为 `0600`，目录权限设为 `0700`；也可用 `TRACEMEMO_TOKEN_FILE` 指向其他私有文件。TraceMemo 默认只监听 `127.0.0.1:6131`，本助手只监听 `127.0.0.1:6412`。

在平台配置中把业务项目与完整微信群名绑定。采集器要求群名唯一匹配，不模糊猜测，未绑定会话不会查询消息。首次回看 30 天，之后按游标增量读取并保留 24 小时重叠用于补录；本机和 Central 都按消息指纹去重。`POST /api/v1/wechat/scan` 可立即采集并返回各群计数。

只上传文本、引用消息和文件标题；不上传图片、音视频、文件内容、媒体 URL 或完整微信数据库。匹配失败、TraceMemo 未就绪或上传失败时不会推进该群游标。Token 和聊天正文不写入采集日志。Accessibility 快照接口只用于手动只读诊断，不参与自动采集，也不会操作微信界面。

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

确认 TraceMemo 与本机 Central 就绪后，可安装登录常驻：

    export CENTRAL_URL=http://127.0.0.1:8080
    export COLLECTOR_TOKEN='与中央服务一致的 token'
    export USER_ID='你的平台用户标识'
    python3 apps/wechat-mac-helper/install_macos.py

安装后使用 macOS LaunchAgent 常驻；助手自己按本机时区执行 09:00、09:30 ... 19:30、20:00 的采集槽。

卸载常驻服务但保留本地配置与去重状态：

    python3 apps/wechat-mac-helper/uninstall_macos.py

LaunchAgent 需读取私有 Token 文件，无需 macOS Accessibility 权限。
