# Muse P9｜只读 Codex 执行看板

基于 P8 `38733f9`；Draft，不合并。

新增 `/api/v1/personal-agent/codex-board`，使用独立 `CAO_MUSE_BOARD_TOKEN`，不接受执行/采集令牌。端点按当前 Muse capability 和明确授权的项目仓库对过滤，最多50项目、每项目5任务。工作区只读观察有界并发/超时，Host 断联或替换的 harness 不报告 running。进展/测试只来自 task+execution 精确相关事件，不推测文件、百分比、ETA或验收完成。

`bindings.board_enabled=true` 是只读登记；不等于 `personal_enabled=true` 的执行授权。`display_alias` 为可展示项目名，事件作者还需显式 `board_event_user_id`（未配置则不展示事件内容/测试）；文件名摘要还需 `board_file_details_enabled=true`。`codex_board_sessions` 只能登记显式授权的工作区、terminal与原harness，foreign会话不取得反馈权，不自动扫描其他本机 Codex 数据。

覆盖数仅针对授权绑定；未接入的本机项目数为未知。其他 Codex Desktop / CLI 的来源适配尚待选定授权项目后接入。P10复用既有受控反馈API，读token不能执行，不增加暂停/终止/自动启动等写入口。

2026-10-12：新增21项边界测试；独立回环只读服务实查登记项目1、有效观察项目0、未覆盖未知。旧 Host manifest 不存在，不能把历史任务作为当前活动会话。真实多项目与原会话反馈仍未验收；设备未烧录本轮固件。

本地全量392项Python测试、40项前端测试通过；配套P2单测未退化。

## 2026-10-12｜用户授权全部已登记本地项目只读接入

新增 `codex_desktop_collector.py`，只调用初始化与 scoped `thread/list`（state DB only，不扫描修复其他会话）；按17个登记项目及Git元数据确认的工作区读取确切日志文件尾部。日志不离开采集进程；输出仅为匿名ID、安全元数据、真实文件/工具/生命周期事件和可证明的测试数。

私有清单与本机launch agent已部署，摘要15秒更新、45秒过期；新只读App Server不持有桌面运行态，notLoaded不映射idle/running。无生命周期只显示unknown，历史结束为ended_unverified。只读器不发送resume/turn/start，也不会给桌面会话写权限。

CAO摘要端点校验独立读token、当前Muse capability和全部授权项目ID集合，投影缺失/撤权/过期返回unavailable；服务只挂载独立投影目录。真实回环复验18个登记绑定（含原测试）、17个桌面项目、38会话。405项Python、40项前端测试通过；本轮没有新增任何项目执行授权。

用户已烧录配套app并获得USB/Audio/语音Ready，屏幕与语音体验仍待用户确认；不能把只读接入当作P10控制通过。

官方读取协议：https://learn.chatgpt.com/docs/app-server
