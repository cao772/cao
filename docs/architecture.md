# 总体架构

## 1. 产品定位

AI Dev Management 是“多项目 + 多开发人员 + 多 Coding Agent”的研发感知与协同平台。它不替代 Codex、TRAE、Claude Code、Hermes、GitHub/GitLab，而是在这些工具之上建立统一的事实层、证据层和项目状态层。

核心原则：

1. **本地事实与远端事实分开采集**：远端 GitHub/GitLab 由中央统一同步；开发者电脑只采集中央看不到的本地工作区状态。
2. **一个业务项目可对应多个仓库**：前端、算法、后端、插件仓库可以统一归属于一个 `project.id`。
3. **事实与 AI 推断分开**：Git、测试、文件变化、MR/PR、CI、Deployment 是事实；AI 只负责摘要、解释和风险提示。
4. **默认最小上传**：源码和项目文档默认不上传中央，只上报元数据、Git 统计、测试结果和结构化摘要。
5. **项目自描述**：每个受管项目根目录用 `project.yaml` 定义项目身份、多个仓库、路径、扫描范围和隐私模式。
6. **完成必须有证据闭环**：Agent 的“完成”声明不能直接转成“正式完成”。

## 2. 组件

```text
开发人员电脑（Docker Desktop）
┌───────────────────────────────────────────────┐
│ Project Sentinel                              │
│                                               │
│ Project Discovery                             │
│ Document Intelligence / Project Memory        │
│ Multi-repository Git Inspector                │
│ Local Git Diff Semantic Analysis              │
│ Agent Event / MCP（后续）                     │
└────────────────────┬──────────────────────────┘
                     │ LocalSnapshot
                     ▼

中央平台
┌──────────────────────────────────────────────────────────────┐
│ Project API                                                  │
│ Snapshot / AgentEvent / RemoteEvent                          │
├──────────────────────────────────────────────────────────────┤
│ Cross-workspace Evidence Fusion                              │
│ 多开发人员 + 多设备 + 多本地仓库                             │
├──────────────────────────────────────────────────────────────┤
│ Remote Evidence Fusion                                       │
│ Commit + MR/PR + CI/Pipeline + Merge + Deployment            │
├──────────────────────────────────────────────────────────────┤
│ Project / Task State + Timeline + Report                     │
├──────────────────────────────────────────────────────────────┤
│ SQLite(MVP) → PostgreSQL                                     │
└─────────────────────▲────────────────────────────────────────┘
                      │ RemoteEvent
┌─────────────────────┴────────────────────────────────────────┐
│ Central DevOps Collectors                                    │
│                                                              │
│ GitLab direct adapter（当前）                                │
│ DevLake adapter（后续扩展）                                  │
│ GitHub adapter（后续扩展）                                   │
└─────────────────────┬────────────────────────────────────────┘
                      │
              GitLab / GitHub / CI
```

## 3. Local Sentinel

Sentinel 只负责“开发者电脑上独有的事实”：

- 自动发现 `/projects/*/project.yaml`；
- 一个 `project.yaml` 可以声明多个 `repositories`；
- 每个 repo 分别读取 branch、HEAD、upstream、ahead/behind；
- 聚合所有 repo 的 modified/added/deleted/untracked 与 diff stat；
- 本机解析未提交 Git diff，只上传结构化代码变化摘要；
- 增量解析允许的 Word/Excel/CSV/PDF/Markdown 等项目资料；
- 维护 Project Memory；
- 解析允许的测试结果；
- 后续通过 MCP 接收 Codex/TRAE/Hermes 的结构化任务事件。

Sentinel **不负责**重复轮询 GitLab/GitHub。

## 4. 中央 GitLab Collector

当前已实现 `apps/remote-collector/gitlab_collector.py`。它部署在能访问公司 GitLab 的中央机器，统一读取 `config/gitlab-projects.yaml`。

当前采集：

- Commit；
- Merge Request；
- Pipeline/CI；
- Deployment（GitLab 实例支持时）。

所有记录标准化为 `/api/v1/remote-events`。

开发人员电脑不需要保存 GitLab API Token。Token 只存在中央 Collector 环境变量或 Secret Store。

当前已登记真实仓库：

```text
low-voltage
├─ Front-end/voltage-management.git
└─ algorithm.git

power-defect-agent
└─ multimodal-agent.git

hyclaw-plugins
└─ hyclaw-plugins.git
```

## 5. Remote Event 关联

远端事实并不总带任务名称。例如 GitLab Pipeline 常只有 `sha` 和 `ref`。

因此采用两阶段关联：

```text
第一阶段
MR标题 / Commit message / branch中的任务ID
              ↓
        关联到项目任务
              ↓
     建立 repo + SHA / branch 映射

第二阶段
Pipeline / Deployment
只有 SHA / ref
              ↓
通过 repo + SHA / branch
继承同一任务身份
```

这样 MR、Pipeline、Deployment 可以组成一个远端证据链，而不要求每条 GitLab 记录都写任务 ID。

## 6. Evidence Fusion

```text
项目资料
  +
多人本地 Workspace
  +
多 Git repo 本地改动
  +
Agent Event
  +
本地 Test
  +
GitLab/GitHub Remote Event
        ↓
任务级 Evidence Fusion
```

典型状态：

```text
待开发
→ 开发中，本地有未提交修改
→ 本地验证通过，尚未提交
→ 已提交远端
→ PR/MR审核中
→ CI通过，待合并
→ 已合并，待部署确认
→ 正式完成
```

失败优先：

- 本地/远端测试失败；
- CI/Pipeline failed；
- Deployment failed；
- 显式 Blocker。

## 7. 正式完成口径

当前系统只有在同一任务关联到：

```text
CI/Pipeline success
+
MR/PR merged
+
Deployment success
```

时才允许状态为 `completed / 正式完成`。

如果项目没有 Deployment 流程，后续会在项目 manifest 中增加可配置的“完成门槛”，而不是偷偷降低全局口径。

## 8. 进度原则

- 有正式任务体系：后续按任务权重/里程碑计算正式进度；
- 无任务体系：不显示伪精确百分比；
- AI 不允许从聊天、提交次数或代码行数猜百分比；
- 代码量只作为开发活动事实，不等于业务完成度。

## 9. 触发机制

```text
Local
文件/Git/测试/Agent变化 → 增量快照
15分钟 → 一致性兜底扫描

Remote
GitLab Collector 默认5分钟轮询
后续增加 Webhook / DevLake

Project
证据变化 → 重新计算任务状态
每天 → 日报
每周 → 周报/跨项目风险
```

## 10. 实现阶段

### Phase 0
架构、`project.yaml`、事件模型、安全边界、Docker 骨架。

### Phase 1（核心已实现）
Local Sentinel、资料增量分析、多工作区聚合、代码变更语义分析、Evidence Fusion。

### Phase 2（进行中）
多仓库、GitLab Remote Collector、Commit/MR/CI/Deployment 远端证据。下一步实测公司 GitLab，并补 Webhook/DevLake/GitHub adapter。

### Phase 3
通过 MCP/Telemetry 接 Codex、TRAE、Hermes、Claude Code 等 Agent。

### Phase 4
项目驾驶舱、日报、周报、跨项目问答、阻塞/风险识别。
