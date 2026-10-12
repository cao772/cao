# Muse P9｜只读 Codex 执行看板

基于 P8 `38733f9`；Draft，不合并。

新增 `/api/v1/personal-agent/codex-board`，使用独立 `CAO_MUSE_BOARD_TOKEN`，不接受执行/采集令牌。端点按当前 Muse capability 和明确授权的项目仓库对过滤，最多50项目、每项目5任务。工作区只读观察有界并发/超时，Host 断联或替换的 harness 不报告 running。进展/测试只来自 task+execution 精确相关事件，不推测文件、百分比、ETA或验收完成。

`bindings.board_enabled=true` 是只读登记；不等于 `personal_enabled=true` 的执行授权。`display_alias` 为可展示项目名，事件作者还需显式 `board_event_user_id`（未配置则不展示事件内容/测试）；文件名摘要还需 `board_file_details_enabled=true`。`codex_board_sessions` 只能登记显式授权的工作区、terminal与原harness，foreign会话不取得反馈权，不自动扫描其他本机 Codex 数据。

覆盖数仅针对授权绑定；未接入的本机项目数为未知。其他 Codex Desktop / CLI 的来源适配尚待选定授权项目后接入。P10复用既有受控反馈API，读token不能执行，不增加暂停/终止/自动启动等写入口。

2026-10-12：新增21项边界测试；独立回环只读服务实查登记项目1、有效观察项目0、未覆盖未知。旧 Host manifest 不存在，不能把历史任务作为当前活动会话。真实多项目与原会话反馈仍未验收；设备未烧录本轮固件。

本地全量392项Python测试、40项前端测试通过；配套P2单测未退化。
