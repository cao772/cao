# AI Dev Management

面向多项目、多开发人员、多 Coding Agent 的研发感知与协同管理平台。

当前已完成 **Phase 1 本地感知核心闭环**，正在推进 **Phase 2 远端证据融合 + Phase 3 Coding Agent MCP 接入**。

核心目标：
- 本地 Project Sentinel 感知 Git 尚未提交的真实开发现场；
- 一个业务项目可以同时关联多个代码仓库，例如“低电压”同时包含前端和算法仓库；
- 中央统一采集 GitLab/GitHub 的 Push、Commit、MR/PR、CI/Pipeline、Deployment 事实；
- 本地 MCP 给 Codex/TRAE/Hermes 等 Agent 提供共享项目上下文，并接收结构化任务事件；
- 融合项目资料、多人本地工作区、测试、Agent 与远端 DevOps 证据；
- 只有证据闭环后才判断任务状态，AI 不凭聊天或代码量猜项目进度；
- 默认不上传源码与项目文档全文，只上传结构化状态与必要摘要。

## 当前代码

```text
apps/
├── local-sentinel/
│   ├── sentinel.py             # 本地项目/多 Git repo 感知
│   ├── multi_repository.py     # 一个项目多个本地仓库聚合
│   ├── document_pipeline.py    # 项目资料增量解析与 Project Memory
│   ├── git_change_analysis.py  # 本地未提交代码变化语义分析
│   ├── agent_bridge.py         # Coding Agent ↔ Project Sentinel/Central 结构化桥接
│   ├── mcp_server.py           # Streamable HTTP MCP Server
│   └── tests/
├── remote-collector/
│   ├── gitlab_collector.py     # 中央 GitLab Push/Commit/MR/CI/Deployment 采集
│   └── tests/
└── server/
    ├── main.py                 # 中央 API（MVP 使用 SQLite）
    ├── project_evidence.py     # 多人/多工作区本地证据融合
    ├── remote_evidence.py      # GitLab/GitHub 远端证据融合
    └── tests/

config/gitlab-projects.yaml      # 当前真实 GitLab 项目/仓库登记
deployments/local/
deployments/central/
docs/
examples/
schemas/project.schema.json
```

## 已登记的真实 GitLab 仓库

当前 `config/gitlab-projects.yaml` 已登记：

```text
低电压项目
├── frontend
│   http://git.hyetec.com/hyetec/rj26nw011/Front-end/voltage-management.git
└── algorithm
    http://git.hyetec.com/hyetec/rj26nw011/algorithm.git

电力设备缺陷处置
└── http://git.hyetec.com/hyetec/rj26nw025/multimodal-agent.git

HyClaw Plugins
└── http://git.hyetec.com/hyetec/rrj26rj001/hyclaw/plugins/hyclaw-plugins.git
```

GitLab Token 不写入仓库配置，只通过中央 Collector 环境变量提供。

## 当前完整链路

```text
开发人员电脑
┌─────────────────────────────────────────────────┐
│ Project Sentinel                                │
│                                                 │
│ 项目资料 → 增量解析 → Project Memory             │
│ repo A  ─┐                                      │
│ repo B  ─┼→ Git状态 + 本地diff语义分析            │
│ repo C  ─┘                                      │
│                                                 │
│ Local Agent MCP                                 │
│ Codex / TRAE / Hermes                           │
│  ├─ get_context                                 │
│  ├─ get_tasks                                   │
│  └─ report started/progress/test/blocker/finish │
└──────────────────┬──────────────────────────────┘
                   │ Local Snapshot / Agent Event
                   ▼
              Central API
                   ▲
                   │ Remote Event
┌──────────────────┴──────────────────────────────┐
│ Central GitLab Collector                        │
│ Push / Commit / MR / Pipeline / Deployment      │
└──────────────────┬──────────────────────────────┘
                   │
               GitLab/GitHub

中央：
Project Memory
+ Local Git / Test
+ Agent Event
+ Remote DevOps Evidence
              ↓
        Evidence Fusion
              ↓
待开发 / 开发中 / 尚未提交 / 已提交远端 /
MR审核中 / CI通过待合并 / 已合并待部署 / 正式完成
```

## “正式完成”的判断

Agent 说“完成”不能直接把任务改成完成。

当前状态链：

```text
本地修改
  ↓
本地测试通过
  ↓
本地验证通过，待远端复核
  ↓ GitLab Commit/Push
已提交远端
  ↓ MR/PR
审核中
  ↓ CI/Pipeline
CI通过，待合并
  ↓ Merge
已合并，待部署确认
  ↓ Deployment success
正式完成
```

如果 CI 或部署失败，优先进入“需要关注”。

## 项目目录与多仓库

每个受管项目目录只需要有一个 `project.yaml`。目录可以同时放项目资料和多个 Git clone：

```text
company-projects/
└── low-voltage/
    ├── project.yaml
    ├── algorithm-ryj/          # algorithm.git
    ├── voltage-management/     # Front-end/voltage-management.git
    ├── 需求拆解.xlsx
    ├── 测试结果.xlsx
    └── 问题反馈.xlsx
```

`project.yaml` 使用：

```yaml
repositories:
  - id: low-voltage-algorithm
    role: algorithm
    provider: gitlab
    url: http://git.hyetec.com/hyetec/rj26nw011/algorithm.git
    local_path: algorithm-ryj
    primary: true

  - id: low-voltage-frontend
    role: frontend
    provider: gitlab
    url: http://git.hyetec.com/hyetec/rj26nw011/Front-end/voltage-management.git
    local_path: voltage-management
```

旧版单 `repository:` 写法仍兼容。

## 项目资料分析

默认 `security.mode: metadata_only`，不会读取项目文件正文。

启用本机资料分析：

```yaml
security:
  mode: local_analysis

analysis:
  enabled: true
  include:
    - documents
    - tests
    - outputs
  use_llm: false
```

支持文本/Markdown/JSON/YAML、DOCX、XLSX、CSV、文本型 PDF；只有新增或 hash 变化的文件重新分析。源码正文默认不上送中央。

## Coding Agent MCP

本地 compose 现在默认同时启动 `sentinel` 和 `agent-mcp`。

MCP 地址：

```text
http://127.0.0.1:6410/mcp
```

默认仅绑定 loopback，不暴露给局域网。将该 URL 添加到 Codex、TRAE、Hermes 或其他支持 Streamable HTTP MCP 的客户端即可。

主要工具：

```text
list_projects
get_context
get_tasks
report_task_started
report_task_progress
report_test_result
report_blocker
report_task_finished
```

`report_task_finished` 只表示 Agent 的本地工作结束；正式完成仍由 Evidence Fusion 根据 Git、测试、MR/PR、CI、Merge、Deployment 判断。

详见 `docs/agent-mcp.md`。

## 快速启动

### 1. 中央 API

```bash
export COLLECTOR_TOKEN='replace-with-a-random-token'
docker compose -f deployments/central/docker-compose.yml up --build -d
curl http://localhost:8080/health
```

### 2. 开发人员本地 Sentinel + MCP

```bash
export PROJECTS_PATH='/Users/you/company-projects'
export CENTRAL_URL='http://host.docker.internal:8080'
export COLLECTOR_TOKEN='replace-with-a-random-token'
export USER_ID='your-name'
export DEVICE_ID='your-device'

# 当前 MCP 实例对应哪个 Agent
export AGENT_VENDOR='OpenAI'
export AGENT_NAME='Codex'
export AGENT_INSTANCE_ID='codex-main'
export MCP_PORT='6410'

docker compose -f deployments/local/docker-compose.yml up --build -d
```

### 3. 中央启用 GitLab Collector

必须在能访问 `git.hyetec.com` 的公司网络/VPN环境运行：

```bash
export COLLECTOR_TOKEN='replace-with-a-random-token'
export GITLAB_BASE_URL='http://git.hyetec.com'
export GITLAB_TOKEN='your-read-api-token'

docker compose \
  -f deployments/central/docker-compose.yml \
  --profile gitlab \
  up --build -d
```

Collector 默认每 5 分钟统一查询已登记仓库。开发人员电脑不重复轮询 GitLab。

### 4. 查看结果

```bash
curl http://localhost:8080/api/v1/projects
curl http://localhost:8080/api/v1/projects/low-voltage/workspaces
curl http://localhost:8080/api/v1/projects/low-voltage/tasks
curl http://localhost:8080/api/v1/projects/low-voltage/remote-events
curl http://localhost:8080/api/v1/projects/low-voltage/evidence
```

## 安全边界

- 项目目录默认 Docker `:ro` 只读挂载；
- `.env`、证书、私钥等敏感文件不读取正文；
- GitLab Token 只存在中央 Collector 环境变量/Secret Store；
- 本地 diff 只在本机分析，中央收到结构化摘要而不是 patch；
- MCP 默认仅监听 `127.0.0.1` 宿主机端口；
- Agent 只上报结构化事件，不要求上传聊天全文；
- `metadata_only` 模式完全不读业务文档正文。

## CI

`cao` 分支 CI 当前覆盖：
- Python compile；
- Document Intelligence；
- nested/multi-repository Git inspection；
- Local Agent Bridge / MCP import；
- cross-workspace Evidence Fusion；
- remote evidence lifecycle；
- GitLab Push/Commit/MR/Pipeline/Deployment normalization；
- GitLab pagination；
- Local Sentinel / Central Server / GitLab Collector Docker 镜像构建。

## 下一步

1. 用公司网络实测 `git.hyetec.com` API 权限与四个真实仓库采集；
2. 实测 Codex / TRAE / Hermes 连接 `http://127.0.0.1:6410/mcp` 并自动上报任务事件；
3. 增加 GitLab Webhook 与 DevLake adapter，定时轮询作为兜底；
4. 建项目总览、任务证据链、人员/Agent、时间线 Web 页面；
5. SQLite MVP 升级 PostgreSQL + 统一 DevEvent 表；
6. 生成日报、周报、风险与跨项目管理驾驶舱。
