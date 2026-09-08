# Evidence Fusion 证据融合

Evidence Fusion 的目标不是让大模型“猜项目完成了多少”，而是把不同来源的研发事实放到同一条证据链中，并保守判断当前状态。

当前 MVP 只使用本地证据：

- 项目资料：需求、任务、测试、阻塞、决策等；
- Local Sentinel：Git branch、HEAD、dirty、ahead/behind；
- Git changed-files 语义分析：本地未提交代码改动的结构化摘要；
- Agent Event：Codex、TRAE、Hermes、Claude Code 等上报的任务/进度/测试/阻塞事件。

远端 PR/MR、CI、部署证据尚未接入，所以当前版本 **不会输出“正式完成”**。

## 状态判断原则

典型状态：

| 状态 | 含义 |
|---|---|
| `planned` | 只有需求/任务定义，未关联实现证据 |
| `in_progress_agent` | Agent 已开始或持续上报进度 |
| `in_progress_uncommitted` | 检测到代码变更，工作区仍有未提交修改 |
| `implementation_detected` | 检测到实现证据，但缺少明确测试/Agent 完成证据 |
| `implementation_tested` | 检测到代码实现及通过测试 |
| `agent_claim_only` | Agent 声称完成，但没有关联代码证据 |
| `implementation_claimed_uncommitted` | Agent 声称完成且有代码改动，但仍未提交 |
| `implementation_claimed_unverified` | Agent 声称完成且有代码改动，但缺少通过测试证据 |
| `test_failing` | 与事项明确关联的测试存在失败/不通过 |
| `blocked` | 与事项明确关联的阻塞证据存在 |
| `locally_complete_uncommitted` | Agent 完成 + 代码实现 + 测试通过，但本地尚未提交 |
| `locally_complete_unpushed` | Agent 完成 + 代码实现 + 测试通过 + 本地提交，但尚未推送 |
| `local_verified_pending_remote` | 本地证据完整，仍等待 PR/MR/CI/部署远端复核 |

## 不强行关联

资料、代码、测试和 Agent 事件通过 `task_id` 或保守的文本相似度关联。

低置信度证据不会强行塞进某个任务。例如一个名为“工程量回归测试：2通过1失败”的测试文件，如果无法高置信度判断它对应哪一条具体需求：

- 该测试保留在 `unlinked_evidence.tests`；
- 项目级仍记录 `global_test_failure_count`；
- 项目进入“需要关注”；
- 不会因为关联不确定而误判某个任务完成或失败。

## Agent Event

中央接口：

```text
POST /api/v1/agent-events
```

建议 Coding Agent/MCP 上报结构：

```json
{
  "schema_version": 1,
  "client_event_id": "optional-idempotency-key",
  "event_type": "task.finished",
  "observed_at": "2026-09-08T17:30:00+08:00",
  "project_id": "low-voltage",
  "user_id": "caoyh",
  "agent": {
    "vendor": "OpenAI",
    "name": "Codex"
  },
  "session_id": "session-123",
  "task_id": "LV-102",
  "task_title": "修复工程量提取问题",
  "data": {
    "summary": "完成扩大工程量清单匹配逻辑修复"
  }
}
```

推荐事件：

```text
task.started
task.progress
task.finished
test.result
blocker.reported
```

MVP 不要求上传 Coding Agent 的完整聊天记录。中央只需要结构化研发事件。

## 查询

```text
GET /api/v1/projects/{project_id}/agent-events
GET /api/v1/projects/{project_id}/evidence
GET /api/v1/projects/{project_id}/current
```

`/current` 同时返回：

- 当前 Git 状态；
- 当前 Project Memory；
- Workspace Inventory；
- Git change analysis；
- 最近 Agent Events；
- `evidence_fusion`。

## 下一层远端证据

接入 Apache DevLake / GitHub / GitLab 后，Evidence Fusion 再增加：

```text
commit pushed
PR / MR opened
review passed
CI passed
merged
deployed
```

只有到那一层，平台才有条件定义组织自己的“正式完成”规则。
