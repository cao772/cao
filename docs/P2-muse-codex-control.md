# P2 Muse → CAO → Superset → Codex

基于 M9 `d377005` 的独立子分支。保留 M9 执行接口、鉴权、请求幂等和 Evidence Fusion；新增受控 profile、真实会话状态、反馈和独立 Muse capability。没有合并正式 cao 或改写 M9 历史。

## 本机模型探测

2026-10-07 使用应用自带 Codex app-server 的 initialize / model/list 实际查询，得到 gpt-6-luna、gpt-6.1-sol、gpt-6-astra 等，均支持 low / medium / high。固定 Superset 源码的 curated catalog 同样包含这三个模型。配置映射 fast=gpt-6-luna，balanced=gpt-6.1-sol，strong=gpt-6-astra；这是本机已验证配置，账户/Host 变化需要重新探测，不能猜测其他账户可用性。

CAO_SUPERSET_CONFIG 在已有 manifest/bindings 之外增加 model_profiles 和 p2_agent_id。p2_agent_id 指向独立 Codex preset（presetId=codex），args 必须严格等于 `apps/server/p2_policy.py` 中的 P2_ARGS：workspace-write、never、禁网络、无额外写目录；只启用并批准 cao-sentinel 的四个执行事件报告工具（report_task_started / progress / test_result / finished），关闭其他 MCP、Apps 与本机已安装插件工具，argv prompt，不能借用旧 --yolo 或 bypass 配置。模型名只由本地管理员配置，API 请求只接受 profile 白名单与三档 effort。实际解析模型写入 execution 展示记录。已有会话暂不热切换模型，Muse 设置作用于下一项任务，避免虚假声称已切换。

## 保护接口

官方 terminal.send 在 Agent 结束时会回退为 shell 输入；agents.run 的 continue 也可能改为新启动。P2 不调用这些反馈路径。`deployments/superset/p2-guard.patch` 为固定源码添加 `terminal.p2Capabilities` 与 `terminal.sendAgent`：校验 workspace、terminal、definition、Codex harness session，调用原 sendAgentMessage，其串行发送链再次检查绑定存活；无 shell 回退、无新建/恢复会话。

先运行 `python3 deployments/superset/install_p2_guard.py ~/Downloads/superset-local`，再重建并重启本机 Host。安装器校验固定 HEAD 和 patch，不覆盖已有修改。CAO 在启动前探测能力；没有补丁时拒绝 P2。Host 仍版本1.36.0，补丁不冒充上游公共 API 或运行源码 SHA 证明。

workspace-write + never + network_access=false + writable_roots=[] 是运行时限制，禁止自动危险命令批准；额外 scope 指令明确禁止 commit/push/merge/deploy/删除仓库或分支/业务数据库写入/正式分支修改。不请求自动越权审批；网络命令/额外写目录和.git写入受sandbox限制。needs_user表示会话等待反馈，Muse不审批。提示词不是完整安全沙箱；不承诺防御同用户权限的恶意 Host、恶意 preset 或人工批准的违规操作。P2 首轮只授权专用测试仓库绑定。Docker Desktop桥接请求必须显式配置CAO_MUSE_BRIDGE_CLIENT，Host端口仍只能发布127.0.0.1，不允许任意私网来源。

## 两种凭据与接口

内部 M9 继续 X-Collector-Token。Muse **不持有该令牌或 Host PSK**。设置一个不同的 CAO_MUSE_TOKEN；Muse 使用 X-Muse-Token，仅可调用 loopback 上 `/api/v1/personal/execution` 的 provider、POST runs、GET runs/{uuid}、POST runs/{uuid}/feedback。只公开 `personal_enabled=true` 的 bindings，不返回 Host配置、环境、prompt、workspace路径、原始terminal、完整会话。scope不能调用项目写接口或任意RPC。反向代理不得为该接口放行非本机客户端。

POST runs 保留 M9 请求字段，增加 model_profile 与 reasoning_effort。Muse task_id 固定派生为 P2-{request_id}，避免复用业务任务。相同 UUID+同内容不启动第二次，同 UUID不同内容409；失败记录不盲重放。结果状态规范化 starting/running/waiting/finished/failed/unknown（queued保留协议词）。agent Stop 是 waiting；Agent/terminal退出是执行进程结束，formal_completion永远false。

反馈包含 request_id UUID、text最长2000字，目标只允许现有execution_id。核对当前Host和绑定后，先持久化unknown，再发送一次。反馈表只保存UUID、execution、内容SHA256、状态、时间，绝不存正文。相同反馈ID不同内容409；超时unknown不重放；finished/unknown不可反馈，也不自动重启。

测试计数只从中央真实 test.result 事件读取，project_id、唯一 task_id、report session_id=execution_id 必须一致。该 report session_id 是事件关联ID，另有 agent_session_id 表示真实Codex harness、session_id表示Superset terminal。不能把三者混为一谈。无真实事件返回null，不解析 DONE 文本或推测测试数。正式完成规则完全未改。

## 验证记录

开发期间只做单元/静态检查；两端完成后统一本机和板端验收。最终实际记录补于本节，未验证部分不得提前标通过。

### 2026-10-07 本机实测及板端问题复核

受限 fast / gpt-6-luna / low 会话 `34388558-2bb0-4f63-b21d-faddaa1272fd` 实际生成 multiply.py 和 unittest。相同会话收到一次反馈后加入严格整数参数验证；相同反馈 request_id 再请求只返回 sent 元数据，没有第二次发送。中央事件报告 7 passed / 0 failed，独立运行 unittest 同样 7 passed。测试仓库 HEAD 保持 fec4047，两个代码文件未提交。

Superset 原生 hook 事件不一定携带 definitionId，因此 guard 允许该字段为空，但必须匹配 workspace、terminal、Codex harness session 与活跃绑定；首次获取 harness 后固定绑定，替换会话返回 unknown。能力探测版本为 guardedAgentSend=2。已逐条审阅并信任固定版本的九个本机通知 hook，没有使用 bypass-hook-trust。仅允许四个事件工具的批准配置使实际事件可以上报，不开放业务写入工具。

第一次板端尝试未启动任务，不能判定验收通过。日志显示项目聚合查询超过 P1 的 5 秒超时；另外无活跃任务的模型问句误走普通聊天。Muse 已将执行启动的只读项目查询改用执行 client 的 60 秒上限，保留 P1 配置，并加入无活跃任务的明确模型答复及不含转录正文的 intent / route_result 诊断。此后发现本机 Host 已离线；恢复服务后旧会话保持 unknown，不重放。板端重新验收仍待完成。

晚间交接：用户决定明天继续。板端同一 execution fd432f08-be0f-4f9d-9bd2-345fa75dc07b 实际收到反馈并加入 addition.py 与八项测试；总计 15 passed / 0 failed，独立 unittest 验证一致，测试仓库 HEAD 仍 fec4047，没有自动提交。用户确认首页 CODEX 状态。随后 Muse 增加 3 秒停顿录音，已烧录、140 tests passed，实机结束时机仍待确认。为降温关闭本轮开发 API 和语音模型，不自动恢复或重放。两边子分支尚未提交/推送/建 P2 Draft PR；明天先恢复本机配置及验证真实 Host 状态，余项详见 Muse project_context/p2-codex-control.md 的暂停交接。

2026-10-08 已整合 ALL 4e08796 的 Personal Agent 只读摘要接口，保留 scoped execution API 独立认证与唯一授权测试仓库。整合后 Python 334 passed、前端 40 passed。Muse 同期整合 ALL bc1af1c，150 passed；手机热点下真机 Wi-Fi / 鉴权 hello / 三次 pong 已恢复，3 秒停顿版收到完整 13.2 秒录音，但整合后的语音执行仍待验收。本 PR 保持 Draft，不将运行时未知或 task.finished 解释为正式项目完成。
