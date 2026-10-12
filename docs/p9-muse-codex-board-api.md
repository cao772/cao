# Muse P9｜CAO Codex 多项目只读汇总 API 设计

> 本提交只冻结契约，尚无新接口或运行验证。上游 [CAO PR #34](https://github.com/cao772/cao/pull/34) HEAD `38733f9` 保持 Draft、未合并。

## 目标

现有 `apps/server/personal_agent_api.py` 通过 `_projects` 与 `_execution_rows` 汇集多个项目，但是不具备合适的、可向 Muse 设备出站的授权边界。现有 `apps/server/execution_p2.py` 的 `personal_auth` 与 `require_muse_run` 能为每个授权执行做单任务安全校验。本阶段扩展 **仅展示必要状态** 的多项目只读快照，不扩大 P2 改代码的权限。

## 只读接口

- `GET /api/v1/personal-agent/codex-board`，`X-Muse-Token`、loopback/已指定 Docker bridge、可配置 scope，按绑定用户/设备/项目/仓库 + `personal_enabled` 同时筛选。
- **绝不**将 `/api/v1/projects` 全局目录或 `/api/v1/execution/runs` 的完整 result_json 直接透传到板端。
- 返回：`snapshot_status`、`observed_at`、`registered_project_count`、`observed_project_count`、`running_count`、`needs_input_count`、`failed_count`、`coverage`、`projects`（最多50）；每项目最近 5 条任务，字段包括匿名/受控 project_id、短别名、repo binding、execution UUID、明确来源/可信时间、状态、测试统计（缺则 null）、最多160字符的脱敏进度摘要。
- 只纳入 **P2 ownership+capability+binding** 严格通过的执行。其它本机 Codex CLI/桌面会话需另设计用户明确授权的项目索引与来源 adapter；未接入必须呈现 untracked，不能声称覆盖所有本地项目。
- 非实时：显示采集/轮询间隔。过期运行状态转 stale/unknown。空成功快照=0；失败或无可信源=未知，不得伪造0。进程结束不等于正式项目验收。
- 不记录/返回 prompt、终端全文、环境变量、用户设备机密、私有路径/凭据；只读令牌不得接受 collector 执行接口。

## 测试门槛

- 401/403、错误/撤销 scope、混合用户设备项目、跨库记录泄漏、与旧非Muse执行隔离；
- 首次成功空快照、Host离线/恢复、陈旧 `running`、重复 session 去重、50项目/每项5任务有界输出；
- 严格字段白名单，无敏感原文；真实已授权多项目只读 API 与 Muse Gateway 联调；不修改现有 P8 只读微信链路。
- 所有写操作在 P9 均禁止，P10 须另行审批和验收。保留 Draft，CI/实际部署结果不预先宣称成功。

任务：[CAO#35](https://github.com/cao772/cao/issues/35) / [Muse#16](https://github.com/cao772/muse/issues/16) / [Muse#17](https://github.com/cao772/muse/issues/17)。
