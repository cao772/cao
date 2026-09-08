# Coding Agent MCP 接入

本地 `agent-mcp` 是 Project Sentinel 的 Coding Agent 入口。它面向 Codex、TRAE、Hermes、Claude Code 等支持 MCP 的客户端，负责两类事情：

1. 给 Agent 提供项目共享上下文；
2. 将 Agent 的任务开始、进度、测试、阻塞和本地完成声明结构化上报中央。

它**不替代 Git / GitLab / CI 证据**，也不会因为 Agent 调用了 `report_task_finished` 就把任务判成正式完成。

## 1. 本地部署

`deployments/local/docker-compose.yml` 默认启动两个服务：

```text
sentinel
  └─ 定时感知本地项目、资料、Git 状态

agent-mcp
  └─ 给本机 Coding Agent 提供 MCP 工具
```

准备环境变量：

```bash
export PROJECTS_PATH='/Users/you/company-projects'
export CENTRAL_URL='http://host.docker.internal:8080'
export COLLECTOR_TOKEN='replace-with-a-random-token'
export USER_ID='caoyh'
export DEVICE_ID='yanhao-macbook'

# 当前 MCP 实例代表哪个 Coding Agent
export AGENT_VENDOR='OpenAI'
export AGENT_NAME='Codex'
export AGENT_INSTANCE_ID='codex-main'
export MCP_PORT='6410'

docker compose -f deployments/local/docker-compose.yml up --build -d
```

MCP 只绑定本机 loopback：

```text
http://127.0.0.1:6410/mcp
```

默认不会暴露给局域网。

## 2. 接入 Codex / TRAE / Hermes

在各客户端的 MCP 配置中添加一个 **Streamable HTTP MCP Server**，地址使用：

```text
http://127.0.0.1:6410/mcp
```

不同客户端的 UI/配置文件位置可能不同，平台侧只依赖上述 MCP URL，不依赖某一家 Agent 的私有会话格式。

如果同一台电脑需要同时区分多个 Agent，建议启动多个本地 compose 实例或不同端口，例如：

```text
Codex   -> 127.0.0.1:6410/mcp  AGENT_NAME=Codex
TRAE    -> 127.0.0.1:6411/mcp  AGENT_NAME=TRAE
Hermes  -> 127.0.0.1:6412/mcp  AGENT_NAME=Hermes
```

这样中央能稳定区分 Agent 身份，不依赖模型每次手工填写名称。

## 3. MCP 工具

### `list_projects`

列出本机 `project.yaml` 已纳管项目，包括一个项目下的多个 Git 仓库。

### `get_context(project_id)`

返回：

- 最新本地 Git 状态（调用时实时刷新）；
- 项目/仓库身份；
- 中央最新 Project Memory；
- 当前任务状态；
- 阻塞、下一步、参与人员与 Agent。

不会返回源码 patch 或项目文档全文。

### `get_tasks(project_id)`

返回中央 Evidence Fusion 后的任务列表与状态。

### `report_task_started`

Agent 开始一项任务。

### `report_task_progress`

上报事实性的开发进展。不要用模型猜测的百分比替代事实。

### `report_test_result`

上报 passed / failed 数量。

### `report_blocker`

上报明确阻塞。

### `report_task_finished`

表示“该 Agent 的本地工作结束”。中央仍继续核验：

```text
本地 Git
+ 测试
+ Push / Commit
+ MR / PR
+ CI
+ Merge
+ Deployment
```

只有远端工程证据满足正式完成规则时，任务才进入 `正式完成`。

## 4. 推荐 Agent 工作约定

每个 Coding Agent 开始工作时建议：

```text
1. list_projects
2. get_context(project_id)
3. report_task_started(...)
```

开发过程中：

```text
report_task_progress(...)
report_test_result(...)
report_blocker(...)
```

准备结束当前 Agent 会话时：

```text
report_task_finished(...)
```

这样新开的 Agent 会话可以通过 `get_context` 恢复项目状态，不再依赖复制上一轮长聊天记录。

## 5. 数据边界

Agent MCP 上报的是结构化活动，不要求上传聊天全文：

```text
project_id
user_id
device_id
agent vendor/name/session
task id/title
event type
summary
test count / blocker
```

项目源码、Git diff 和文档正文继续遵守 `project.yaml` 的 `security.mode`，默认不上传中央。
