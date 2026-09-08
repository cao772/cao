# 总体架构

## 1. 产品定位

AI Dev Management 是“多项目 + 多开发人员 + 多 Coding Agent”的研发感知与协同平台。它不替代 Codex、TRAE、Claude Code、Hermes、GitHub/GitLab，而是在这些工具之上建立统一的事实层和项目状态层。

核心原则：

1. **本地事实与远端事实分开采集**：远端 GitHub/GitLab 由中央 DevOps 采集器统一同步；开发者电脑只采集中央看不到的本地工作区状态。
2. **事实与 AI 推断分开**：Git、测试、文件变化、PR/MR、CI 是事实；AI 只负责摘要、解释、风险提示，不凭空计算进度。
3. **默认最小上传**：源码和项目文档默认不上传中央，只上报元数据、Git 统计、测试结果、结构化摘要。
4. **项目自描述**：每个受管项目根目录必须有 `project.yaml`，定义项目身份、路径、扫描范围、隐私模式和仓库映射。
5. **事件统一**：本地 Collector、Agent、GitHub/GitLab、CI 都转换成统一 `DevEvent`，再由 Evidence Fusion Engine 关联。

## 2. 组件

```text
开发人员电脑（Docker Desktop）
┌──────────────────────────────────────┐
│ Project Sentinel                     │
│  - Project Discovery                 │
│  - Filesystem Watcher                │
│  - Git Inspector                     │
│  - Test Result Parser                │
│  - Local Snapshot                    │
│  - MCP Server                        │
│  - Event Uploader                    │
└──────────────────┬───────────────────┘
                   │ HTTPS / Event API
                   ▼
中央平台
┌────────────────────────────────────────────────────────┐
│ Project API                                             │
│  - Project Registry                                     │
│  - Event Ingest                                         │
│  - Timeline                                              │
│  - Snapshot Query                                        │
├────────────────────────────────────────────────────────┤
│ Evidence Fusion Engine                                  │
│  本地工作区 + Agent 声明 + Git 远端 + PR/MR + CI + Test │
├────────────────────────────────────────────────────────┤
│ Progress / Report Engine                                │
│  项目阶段、完成事实、进行中、阻塞、风险、日报、周报     │
├────────────────────────────────────────────────────────┤
│ PostgreSQL / Redis                                      │
└───────────────┬───────────────────────┬────────────────┘
                │                       │
          Apache DevLake             Langfuse(二期)
                │                       │
         GitHub/GitLab/CI        Agent Trace/Session
```

## 3. Local Sentinel 职责

Sentinel 只负责本机开发现场：

- 自动发现 `/projects/*/project.yaml`；
- 读取当前 branch、HEAD、upstream、ahead/behind；
- 统计 modified/added/deleted/untracked；
- 统计 diff 行数和未 push commit；
- 追踪允许目录的文件新增/修改/删除元数据；
- 解析允许的测试结果；
- 接收 Codex/TRAE/Hermes 等 Agent 的 MCP 上报；
- 生成 `LocalSnapshot` 并发送中央。

Sentinel **不负责**重复轮询整个 GitHub/GitLab；远端事实由中央统一采集。

## 4. 中央远端采集

第一阶段先定义适配器接口；第二阶段接 Apache DevLake：

- Commit / Branch / Contributor；
- Pull Request / Merge Request / Review；
- Issue；
- CI / Pipeline；
- Deployment（有条件时）。

## 5. Evidence Fusion

任何“完成”都不能只相信 Agent 文本。典型融合规则：

```text
Agent: task finished
  + local changed files
  + tests passed
  + commit exists
  + push exists
  + PR/MR status
  + CI status
= evidence-backed task state
```

示例：Agent 上报“完成”，但本地仍有未提交修改，则平台展示“开发完成/尚未提交”，而不是“已交付”。

## 6. 进度原则

- 有正式任务体系：按任务权重/里程碑计算正式进度；
- 无任务体系：不显示伪精确百分比，只显示阶段、近期完成、进行中、阻塞、活跃度和证据；
- AI 不允许从聊天或代码量猜测百分比。

## 7. 触发机制

采用“事件驱动 + 定时兜底”：

- 文件变化 / Git 变化 / 测试结果 / Agent 上报 → 增量快照；
- 每 15 分钟 → 轻量一致性检查；
- 每天固定时间 → 完整日快照与日报；
- 周期性 → 周报与跨项目风险汇总。

## 8. 实现阶段

### Phase 0
架构、`project.yaml`、事件模型、安全边界、Docker 骨架。

### Phase 1
Local Sentinel → 中央 API → PostgreSQL → 项目列表/时间线，完成“本地多个项目持续上报”的闭环。

### Phase 2
接 DevLake，融合 GitHub/GitLab/CI/PR/MR 远端事实。

### Phase 3
通过 MCP/Telemetry 接 Codex、TRAE、Hermes、Claude Code 等 Agent。

### Phase 4
日报、周报、跨项目问答、阻塞/风险识别和项目经理驾驶舱。
