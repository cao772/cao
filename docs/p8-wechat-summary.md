# P8｜Muse 微信只读摘要

新增 `GET /api/v1/personal-agent/wechat-notifications`。只接受独立
`CAO_MUSE_WECHAT_TOKEN`（至少 32 字符）；不能等于采集令牌或执行令牌。
复用 header `X-Muse-Token`，仅允许回环或明确指定的 Docker bridge 单一客户端。
这是只读端点，不启动采集、不控制 Codex、不发送微信。

## 来源与部署

采集助手从既有 `wechat-config.json` 授权群构建独立 `muse-readonly` 投影目录：

- `wechat-config.json`：仅 enabled、项目/精确群名绑定、generated_at；每约 20 秒更新，保存授权配置时立即更新。
- `wechat-muse-health.json`：当前 scope 的状态与最近完整成功批次时间。成功空批次有效；失败/停用批次 invalidates availability。
- 投影只在 Mac 私有目录，不能进入 Git；目录 0700、文件 0600。不包含 TraceMemo、采集器或 Muse 密钥。

CAO 配置 `CAO_WECHAT_STATE_ROOT` 指向只读挂载的投影目录，显式设置
`CAO_WECHAT_USER_ID` 和 `CAO_WECHAT_DEVICE_ID`，值必须来自当前采集助手身份。
不挂载完整采集器状态根目录，也不凭数据库里的项目名猜授权。

每次请求重新读当前投影，超过 60 秒不可用。scope 为用户、设备、排序去重的项目/群
配对哈希；授权范围发生变化时 scope 改变，Muse 必须重新核对范围后更新本地 scope。
原始 config 文件被外部修改的撤销最长约 20 秒传播至投影，再按 Muse 60 秒轮询刷新。
通过助手配置 API 的撤销立即更新投影。这个批次源并非实时消息推送。

## 白名单响应

schema_version=1，scope_id（64位十六进制哈希），authorized=true，status（available/stale/unavailable），
last_success_at（带时区 ISO 时间或 null），complete=true，events（仅匿名 event_id 和 category）。
类别：mention/task/decision/blocker/other；沿用已有分类标签，不读取正文做新分类，不能把未提供的 mention 当已验证 @本人。

查询同时限制用户、设备、项目、精确群名、source=wechat_personal；仅读取指纹和类别。
仅返回最近 30 天、最多 1000 个完整事件；超限返回 unavailable，不能用截断数据推进基线。
缺配置/授权停用/投影失效为 503；无成功健康记录或采集失败为 unavailable；成功批次超过 90 分钟为 stale。
不会返回正文、发送者、群名、项目名、附件或凭据。

## 验证

370 项 Python、40 项前端测试通过；新增混合用户/设备/项目/群的隔离、令牌与非回环拒绝、
授权撤销/scope 变化、空批次/失败状态、投影字段最小化测试。
本机沿用三个既有授权群：首次批次新增 3/重复 56/失败 0，重复采集新增 0/重复 59/失败 0。
只读测试服务在回环 8091，生产数据库卷只读，未替换原执行服务；真实摘要 558 个匿名事件。
Muse 首次/重复读取都是静默基线 0，而非微信未读为零。

实体板展示及语音验收交由 Muse PR #15 记录。此分支基于 P3 精确 HEAD 01fd970，
PR 保持 Draft，不能据此宣称其他上游分支已经合并。
