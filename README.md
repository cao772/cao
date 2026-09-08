# AI Dev Management

面向多项目、多开发人员、多 Coding Agent 的研发感知与协同管理平台。

当前已进入 **Phase 1：本地项目感知 + 项目资料增量分析**。

核心目标：
- 本地 Project Sentinel 感知 Git 尚未提交的真实开发现场；
- 中央统一融合 GitHub/GitLab、测试、Agent 与项目资料证据；
- 以 `project.yaml` 作为项目机器可读身份与扫描规范；
- 事实由程序采集，AI 只负责摘要与解释，不凭空估算项目进度；
- 默认不上传源码与项目文档全文，只上传结构化状态与必要摘要。

## 当前代码

```text
apps/
├── local-sentinel/
│   ├── sentinel.py             # 本地项目/Git 感知
│   ├── document_pipeline.py    # 项目资料增量解析与 Project Memory
│   └── tests/
└── server/                     # 中央接收 API（MVP 使用 SQLite）

deployments/
├── local/
└── central/

docs/
├── architecture.md
├── project-spec.md
├── event-model.md
├── security.md
└── document-intelligence.md

examples/project.yaml
schemas/project.schema.json
```

## 当前链路

```text
开发者项目目录
  ↓ 只读挂载
Project Sentinel
  ├─ Git 状态 / 文件元数据
  └─ local_analysis 模式下：项目资料增量解析
           ↓
      本地 SQLite hash 缓存
           ↓
      Word / Excel / 文本解析
           ↓
      文档角色 + 结构化事实
           ↓
        Project Memory
  ↓
Central API
  ↓
SQLite（MVP）
  ↓
项目列表 / 项目快照 API
```

## 项目资料分析

默认 `security.mode: metadata_only`，不会读取项目文件正文。

需要启用本机资料分析时，在项目 `project.yaml` 中设置：

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

第一版支持 `.md/.txt/.json/.yaml`、常见源码文本、`.docx`、`.xlsx`。只有新增或 hash 发生变化的文件重新分析；结果缓存在 Sentinel 自己的 `/state` Docker volume，不写入项目目录。

如需使用本机 OpenAI-compatible 模型：

```bash
export LOCAL_LLM_BASE_URL='http://host.docker.internal:11434/v1'
export LOCAL_LLM_MODEL='qwen3:8b'
```

并把 `analysis.use_llm` 改为 `true`。默认禁止把正文发送到非本机分析地址。

详细规则见 `docs/document-intelligence.md`。

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

返回的 `payload.analysis` 中可以看到文档角色、增量分析统计、结构化 facts 与当前 Project Memory。

## 本轮验证

已在本地完成：
- Python 语法编译检查；
- 增量文本分析单元测试：首次分析、第二次命中缓存；
- `.docx` 段落解析 smoke test；
- `.xlsx` 只读抽样解析 smoke test。

尚未在真实 Docker Desktop + 真实项目目录上完成端到端验证。

## 下一步

1. 加入 watchdog 文件事件，进一步减少周期扫描与重复 hash；
2. 针对 Git changed files 做代码变化语义分析，而不是全量源码扫描；
3. 将中央 SQLite MVP 升级为 PostgreSQL + 统一 `DevEvent` 表；
4. 做项目总览、Project Memory 和时间线 Web 页；
5. 接入 Apache DevLake，同步 GitHub/GitLab/PR/MR/CI 远端事实；
6. 增加 MCP Server，让 Codex/TRAE/Hermes 结构化上报任务、测试和阻塞。
