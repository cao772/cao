# M9 本地 Superset 执行切片

CAO 保存业务项目、仓库、手动任务及执行记录；Superset 负责 worktree、终端与 Codex。没有复制 Superset runtime，没有修改 Evidence Fusion。正式完成不能由进程退出或 Agent 声明决定。

## PR27 合并后的最终组合验收，2026-10-07

- 正式基线为 PR27 merge commit `43fb4a93118a7baa47a319a691b03a048729092a`。以普通 merge 合入 M9；两个父提交为原 M9 `007a7847b1cc06001a08ed55d5cb6581ffbc70f9` 与该正式基线，未 rebase、squash 或 force push。
- index.html 自动合并，没有未解决冲突。对照新 origin/cao，该文件仅新增“开发执行”入口，PR27 产品结构完整保留。此次没有扩功能或导入真实业务仓库。
- 全新组合回归310 Python /40前端通过，全部JS语法检查通过。Server/Web从组合分支直接重建，未再使用临时叠加目录。生产FastAPI63个路由方法组合无重复；Web资源实装检查通过。
- 真实浏览器105项检查通过：24项目可读，411原材料与123页目录索引分开统计，目录不计入材料版本/变化/冲突；当前工作正常展示，下一步不借用当前工作或全局日期；无JS/API错误，开发执行入口恰好一个。兼容可启动、不兼容禁用的执行页检查再次通过。
- 新模型任务 `M9-REAL-20261007-3628c838`：Workspace `f122bcdd-84a0-4b9a-9e3a-663b2cb7f997`，Terminal `9d206f7d-ccec-4d38-825d-623866be8ac9`。通过新部署的CAO启动Superset Codex，实际编写两份Python文件、10测试通过，验收方独立重跑10/0。
- 从该新会话核对get_context/get_tasks及四类上报调用，中央新事件ID9/10/11/12对应started/progress/test.result/finished。Agent回复DONE；CAO检查仍为formal_completion=false、runtime_status=running，未把本地声明变成正式完成，也未把空闲交互进程标成退出。
- 测试代码仅在公开空仓库的本地隔离worktree中，未提交或推送到该测试仓库。审查包只含脱敏事件和工具调用索引，不含上下文材料正文或完整会话日志。

PR28保持Draft，交给最终审查；真实项目、运行源码SHA证明、自动MCP/Terminal关联及PR/CI回流仍在首版范围之外。

## 第二阶段真实验收，2026-10-07

- PR27 仍 OPEN，正式 cao 仍为 `7d4123c`。本轮没有合并两个 PR，也没有把临时叠加镜像作为最终组合回归证据。
- 每次 workspaces.create、agents.run 前重新查询 health.check；Host version 必须严格为1.36.0，否则拒绝写入。settings.agentConfigs.list 会初始化/补全默认配置，同样受保护。版本阻断记录为 blocked_compatibility，相同请求 ID 不重放。前端禁用不兼容 Host 的启动按钮。
- 支持契约对应源码9a50076；health 不提供源码 SHA，因此 runtime_revision_attested=false。版本检查不能识别保持同一版本号的源码更改，不能冒充运行二进制 SHA 证明。
- 公开 cao772/test 实际为空仓库；clone 后只在本地种下 README/.gitignore 基线 fec4047，再通过 CAO 创建 Superset 隔离 worktree。没有向公开仓库推送任何文件。
- 实际执行 ID / Workspace：`7d966623-18e5-4bf8-9d0f-e66144f95ca9`；Terminal Session：`217f05de-ac9e-4c5f-9e02-e06ac667689b`；任务：`M9-REAL-20261007-c63b7e56`。
- Superset 启动的 Codex 实际编写 title_tools.py、test_title_tools.py，完成 Unicode 空白规范化与类型校验；python3 -m unittest -v 得到10 passed/0 failed。验收方在同一工作区独立重跑，结果相同。
- 核对该 Codex 会话调用记录：get_context/get_tasks 均已调用；中央实际收到 task.started/progress/test.result/finished，事件 ID 为5/6/7/8，测试计数10/0。通过 task_id 对照执行记录；本轮未实现自动将 MCP 事件绑定 Terminal Session 或自动变更 execution 状态。
- 首次连接因会话没有代理环境超时；补齐 Superset Codex 专用 HTTPS_PROXY/HTTP_PROXY 与本机 NO_PROXY 后，服务明确提示 Homebrew Codex0.142.4 太旧。改用本机 ChatGPT 应用自带0.162.0-alpha.2，模型保持原配置。两个失败会话已结束，记录保留，以新请求 ID 启动，未盲重放。
- 中央更新期间首次 started 上报连接中断，Agent 重试后成功；中央核对仅一条 started。测试工作区结果、独立测试日志、脱敏 MCP 调用索引与中央事件纳入审查包，不包含 get_context 返回的项目材料。
- 新独立分支回归：286 Python /26前端通过，全部 JS 语法检查、Server/Web镜像构建、Web资源实装检查通过。真实浏览器检查兼容可启动、不兼容禁用且无JS错误；不兼容页面用响应拦截验证，未改真实Host。

当时的下一门槛为PR27合并及新组合验收；已在上节完成。PR28继续Draft，真实项目尚未接入。

## 本机已验证，2026-10-07

- Superset 官方源码独立目录 `~/Downloads/superset-local`，固定提交 `9a50076c324b3d2575762e5bdcba6838061c8be5`，Bun 1.4.2，Host 1.36.0。
- 用原始 `packages/host-service/build.ts` 构建 Host；Desktop 开发构建提供 Electron/native addons 与 PTY daemon。启动官方 Host 入口，绑定 `127.0.0.1:4879`，独立 SQLite/PSK，无官方 Superset SaaS 登录，health 的 cloudRegistered=false。
- 实测 `health.check`、`project.list/create`、`settings.agentConfigs.list`、`workspaces.create`、`agents.run`、`workspace.get`、`terminal.list/snapshot`。
- 浏览器真实点击 CAO → 本地 Host → 隔离 worktree → Codex session → CAO 检查进程，成功；401 鉴权、同请求 ID 不重复启动、页面无 JS 异常。
- 首版仅导入新建的本地测试仓库，没有导入正式项目；当时仅验证交互进程启动。第二阶段模型任务与 MCP 验收见上节。
- CAO MCP 原有 `cao-sentinel` 配置继续保留。
- 最终切换到已登录本地开发账号的 Desktop Host，CAO 创建的工作区实际出现在 Superset 侧栏，并打开到 `/v2-workspace/{id}`。没有登录官方 SaaS。

## 部署

1. clone 官方源码并固定版本；阅读 README、AGENTS.md 和 setup.local.sh 后安装其依赖。需 Bun 1.4.2、Docker、jq。
2. `bun run dev` 构建 Desktop 原生资源；在 `packages/host-service` 执行 `bun run build:host`。
3. 推荐使用已登录本地开发账号的 Desktop Host。在 CAO 配置中设置 manifest_path 指向 `superset-dev-data/host/<org>/manifest.json`，connect_host 为127.0.0.1（Mac）或host.docker.internal（Docker）。Server只读挂载整个host目录，不能只挂载单个manifest文件，否则原子替换后可能仍读到旧文件。每次调用重新读取端口/令牌；拒绝外部地址。不要把 manifest 放入 Git 或交付包。

也可在 CAO 根目录运行独立 Host（可选路径，不是最终验收的 Desktop Host）：

```sh
python3 deployments/superset/start_host.py --source ~/Downloads/superset-local --state .local/superset-standalone
```

启动器生成权限 0600 的 state/config.json，不打印令牌。它关闭 Host relay 和 Sentry；不更改官方鉴权实现。`AUTH_TOKEN` 为本地开发占位值，不是官方登录凭据，依赖云鉴权的操作不保证支持。Host 入站仍使用真实随机 Bearer PSK。

先通过本地 `project.create` 导入测试仓库，保存返回 projectId。配置 bindings：

```json
{
  "project_id": "cao-platform",
  "repository_id": "local-execution-smoke",
  "superset_project_id": "返回的 Superset projectId",
  "base_branch": "codex/smoke-base"
}
```

同一业务项目可以配置多个 repository_id。调用者不能直接指定任意 repo 路径；所有启动必须匹配配置绑定。首版手动输入任务名称/ID，尚未提供既有 Evidence 任务选择器。

CAO Server 设置 `CAO_SUPERSET_CONFIG` 为上述 JSON 的只读挂载路径。Docker Desktop 中 url 使用 `http://host.docker.internal:4879`；Mac 原生服务使用 `http://127.0.0.1:4879`。不要把 Docker 容器中的 127.0.0.1 当作 Mac。

页面 `/execution.html`，使用现有 COLLECTOR_TOKEN 连接，令牌只保留在当前页面。所有执行接口要求此令牌，未配置令牌则拒绝执行。PSK 不返回前端。

## 契约与失败处理

- API：GET `/api/v1/execution/provider`、GET/POST `/runs`、GET `/runs/{uuid}`，统一带 X-Collector-Token。
- 请求包含 UUID request_id、project_id、repository_id、task_id、task_title、agent=codex、可选 prompt。留空只启动交互进程。
- SQLite 先持久化请求，再创建 Workspace，再启动 Agent；request_id 同时作为 Superset workspace id。相同请求不会重放；同 ID 不同内容返回409。
- 写操作超时/错误记录 unknown，不盲目重试。进程崩溃遗留 creating_workspace/starting_agent 也不会重放，需人工核对 Host。当前尚无自动对账恢复。
- 状态查询从 Host 读取 workspace 和 terminal，runtime_status 为 running/exited/not_observed，均不代表项目正式完成。返回的 session_id 是终端 session，不冒充模型会话 ID。
- 只允许固定本机 HTTP 地址，不跟随重定向、不使用代理环境、不暴露任意 Host RPC 转发。

## 完整开发栈遇到的上游问题

setup.local.sh 的依赖与 Desktop/Web/API 构建成功；Postgres 17 镜像两次下载出现 unexpected EOF。此机器已有 Postgres 16 Alpine，改用独立容器/卷，全部端口限制为127.0.0.1。Redis、neon-proxy、SRH 已运行。

历史 PostgreSQL 迁移存在缺少 pg driver、同事务使用新枚举值的问题。在新建测试库补齐原生pg驱动、auth schema、pg_trgm后，用被忽略的本地Drizzle配置明确 schemaFilter=['public','auth']，执行当前schema push。seed-dev首次因上游team_members.organization_id缺省失败；再次运行现有幂等seed成功，随后通过实际桌面按钮登录，进入工作台。默认团队成员关系未做独立修复/验收。不要用该绕行方案替代生产迁移，不能改写上游 migrations。Host SQLite 路径不依赖该 PostgreSQL 开发栈。

## 代码与运行基线

M9最初基于正式cao `7d4123cc9392075d1fc5254f81f0f48ce32890a1`。PR27合并后，已将正式cao `43fb4a9` 普通merge到M9，并从真实组合分支重建本机镜像。当前回归310 Python/40前端。此前 `.local/m9-runtime` 的临时叠加镜像及275/26、299/40计数仅为历史首版证据，不作为最终合并证明。

边界：Host tRPC 为源码接口，版本固定，不宣称稳定公共 API；CAO deep link、自动同步、PR/CI回流、真实项目接入仍未完成。模型任务与 MCP 已在第二阶段测试工作区验证。切换Host后不会把另一Host的执行错误映射到当前Host。本轮没有 fork 发布 Superset，也没有合并 PR27。
