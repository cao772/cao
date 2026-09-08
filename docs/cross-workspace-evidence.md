# 跨工作区任务级证据融合

## 目标

同一个项目可以由多名开发人员在不同电脑、不同分支、不同 Coding Agent 下协作。平台不能只看最后上传的一个工作区，而需要把同一需求/任务在不同人的本地证据合并成一个项目级状态。

## 输入

每个开发人员最新工作区提供：

- 当前 Git 分支、HEAD、dirty、ahead/behind；
- 本地未提交代码变更的结构化语义摘要；
- 项目资料抽取出的 requirement/task/test/blocker；
- Codex、TRAE、Hermes 等 Agent 的结构化事件。

## 关联规则

1. 明确 `task_id` 相同的证据直接归入同一事项。
2. 没有 task_id 时，使用高阈值标题相似度归并。
3. Agent 事件默认只进入与 `user_id` 相同的开发人员工作区，避免同一 Agent 事件被复制到所有工作区。
4. 不能高置信度关联的代码、测试、Agent 事件、阻塞继续进入 `unlinked_evidence`，不强行绑定。

## 状态原则

负向证据优先：

- 任一相关工作区有阻塞 -> 阻塞；
- 任一相关测试失败 -> 测试未通过；
- 任一相关工作区仍 dirty -> 不能判本地验证完成；
- 任一相关工作区存在未 push 提交 -> 显示尚未推送；
- 只有在 Agent 完成声明 + 实现代码 + 通过测试同时存在，且相关工作区均无 dirty/ahead 时，最多判为“本地验证通过，待远端复核”。

目前仍然不支持“正式完成”。正式完成需要后续接入 PR/MR、CI、Merge 和部署证据。

## API

- `GET /api/v1/projects/{project_id}/evidence`：完整跨工作区证据融合结果。
- `GET /api/v1/projects/{project_id}/tasks`：面向项目管理页面的任务列表与证据摘要。
- `GET /api/v1/projects/{project_id}/current`：项目汇总 + 跨工作区任务证据 + 最近工作区详情。

## 典型例子

同一个“资料上传更新左侧树状页面”任务：

- 开发人员 A / Codex：后端修改完成；
- 开发人员 B / TRAE：前端修改完成并有测试通过；
- 两边工作区都 clean 且无未推送提交。

系统会把两边证据合并到同一 work item，contributors 显示两个人，状态为“本地验证通过，待远端复核”，而不是分别显示成两个无关任务。
