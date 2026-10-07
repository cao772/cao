# M9 本地 Superset 执行切片

CAO 保存业务项目、仓库、手动任务及执行记录；Superset 负责 worktree、终端与 Codex。没有复制 Superset runtime，没有修改 Evidence Fusion。正式完成不能由进程退出或 Agent 声明决定。

## 本机已验证，2026-10-07

- Superset 官方源码独立目录 `~/Downloads/superset-local`，固定提交 `9a50076c324b3d2575762e5bdcba6838061c8be5`，Bun 1.4.2，Host 1.36.0。
- 用原始 `packages/host-service/build.ts` 构建 Host；Desktop 开发构建提供 Electron/native addons 与 PTY daemon。启动官方 Host 入口，绑定 `127.0.0.1:4879`，独立 SQLite/PSK，无官方 Superset SaaS 登录，health 的 cloudRegistered=false。
- 实测 `health.check`、`project.list/create`、`settings.agentConfigs.list`、`workspaces.create`、`agents.run`、`workspace.get`、`terminal.list/snapshot`。
- 浏览器真实点击 CAO → 本地 Host → 隔离 worktree → Codex session → CAO 检查进程，成功；401 鉴权、同请求 ID 不重复启动、页面无 JS 异常。
- 仅导入新建的本地测试仓库，没有导入正式项目。测试只启动交互 Codex，没有提交模型任务或声称 Agent 已完成工作。
- CAO MCP 原有 `cao-sentinel` 配置继续保留。此轮未验证新启动 Agent 实际调用 MCP 或上报任务事件。
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

M9 分支基于正式 cao `7d4123cc9392075d1fc5254f81f0f48ce32890a1`；PR27 尚未合并，未混入 M9 Git 历史。
本机运行镜像由被忽略的 `.local/m9-runtime` 构建，保留原部署 PR27 `93ec253` 再叠加 M9，避免回退现有页面。独立分支回归275 Python/26前端；组合版本299 Python/40前端。合并前仍需以最终cao进行集成验证。

边界：Host tRPC 为源码接口，版本固定，不宣称稳定公共 API；桌面本地登录/共享Host已验证，CAO deep link、自动同步、PR/CI回流、真实项目接入与模型任务验收仍未完成。切换Host后不会把另一Host的执行错误映射到当前Host。本轮没有 fork 发布 Superset，也没有合并 PR27。
