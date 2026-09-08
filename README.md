# AI Dev Management

面向多项目、多开发人员、多 Coding Agent 的研发感知与协同管理平台。

当前已进入 **Phase 0 + Phase 1 最小闭环骨架**。

核心目标：
- 本地 Project Sentinel 感知 Git 尚未提交的真实开发现场；
- 中央统一融合 GitHub/GitLab、测试、Agent 与项目资料证据；
- 以 `project.yaml` 作为项目机器可读身份与扫描规范；
- 事实由程序采集，AI 只负责摘要与解释，不凭空估算项目进度；
- 默认不上传源码与项目文档全文，只上传结构化状态与必要摘要。

## 当前代码

```text
apps/
├── local-sentinel/   # 开发者电脑 Docker Collector
└── server/           # 中央接收 API（MVP 使用 SQLite）

deployments/
├── local/
└── central/

docs/
├── architecture.md
├── project-spec.md
├── event-model.md
└── security.md

examples/project.yaml
schemas/project.schema.json
```

## 当前最小链路

```text
开发者项目目录
  ↓ 只读挂载
Project Sentinel
  ↓ Git/文件元数据快照
Central API
  ↓
SQLite（MVP）
  ↓
项目列表 / 项目快照 API
```

## 快速验证

### 1. 为本地项目增加 `project.yaml`

参考：`examples/project.yaml`。

假设所有受管项目位于：

```text
/Users/you/company-projects/
├── project-a/project.yaml
└── project-b/project.yaml
```

### 2. 启动中央 API

```bash
export COLLECTOR_TOKEN='replace-with-a-random-token'
docker compose -f deployments/central/docker-compose.yml up --build -d
curl http://localhost:8080/health
```

### 3. 启动本地 Sentinel

```bash
export PROJECTS_PATH='/Users/you/company-projects'
export CENTRAL_URL='http://host.docker.internal:8080'
export COLLECTOR_TOKEN='replace-with-a-random-token'
export USER_ID='your-name'
export DEVICE_ID='your-device'

docker compose -f deployments/local/docker-compose.yml up --build -d
```

### 4. 查看采集结果

```bash
curl http://localhost:8080/api/v1/projects
curl http://localhost:8080/api/v1/projects/<project_id>/snapshots
```

## 下一步

1. 为 Sentinel 增加增量状态缓存与文件事件监听，避免周期性重复 hash；
2. 将中央 SQLite MVP 升级为 PostgreSQL + 统一 `DevEvent` 表；
3. 做项目总览和时间线 Web 页；
4. 接入 Apache DevLake，同步 GitHub/GitLab/PR/MR/CI 远端事实；
5. 增加 MCP Server，让 Codex/TRAE/Hermes 结构化上报任务、测试和阻塞。
