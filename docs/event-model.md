# 统一事件模型

所有采集源统一转换为 `DevEvent`。上层时间线、证据融合、日报/周报只依赖事件协议，不直接依赖 Codex、TRAE、GitHub 或 GitLab 的私有格式。

## DevEvent

```json
{
  "event_id": "uuid",
  "schema_version": 1,
  "event_type": "local.git.snapshot",
  "occurred_at": "2026-09-08T16:30:00+08:00",
  "received_at": "2026-09-08T16:30:03+08:00",
  "organization_id": "org-1",
  "project_id": "low-voltage",
  "user_id": "caoyh",
  "device_id": "macbook-air-1",
  "workspace_id": "low-voltage-cyh",
  "source": {
    "kind": "local_sentinel",
    "name": "project-sentinel",
    "version": "0.1.0"
  },
  "correlation": {
    "task_id": "LV-102",
    "agent_session_id": null,
    "commit_sha": null,
    "pull_request_id": null
  },
  "data": {}
}
```

## 第一阶段事件类型

### 本地
- `local.project.discovered`
- `local.project.removed`
- `local.files.changed`
- `local.git.snapshot`
- `local.test.finished`
- `local.snapshot.created`

### Agent
- `agent.session.started`
- `agent.progress.reported`
- `agent.blocker.reported`
- `agent.test.reported`
- `agent.task.finished`

### 远端 Git/DevOps
- `remote.commit.created`
- `remote.pull_request.opened`
- `remote.pull_request.merged`
- `remote.review.created`
- `remote.pipeline.finished`
- `remote.issue.changed`

## 不可变事件 + 可变快照

事件表原则上 append-only。项目当前状态由事件生成 `ProgressSnapshot`，快照可以更新/重建。

这样可以回答：
- 某个状态为什么被判定为“进行中/阻塞/已交付”？
- 当时 Agent 怎么说？
- 本地有没有修改？
- 后来何时 commit/push/PR/CI？

## 证据优先级

默认可信度从高到低：

1. CI / Test 的确定性结果；
2. Git 远端 commit / merge / tag 等事实；
3. 本地 Git / 文件状态；
4. 任务系统人工状态；
5. Agent 自报文本；
6. LLM 推断。

AI 推断永远不能覆盖更高等级的确定性事实。
