# 真实项目目录样本：电力设备缺陷处置

本文件记录第一份真实项目目录样本 `power_defect_agent_handoff.zip` 对平台设计的验证结果，用于后续回归。它不是项目业务真相本身；实际状态仍需结合最新文件、Git、测试和 Agent 证据判断。

## 1. 样本特征

压缩包约包含 1623 个 ZIP 条目。剔除 `__MACOSX` 元数据后，逻辑文件体量约 90.5 MiB。

主要文件类型包括：

- JPG：448
- Markdown：50
- Python：48
- YAML/YML：41
- PNG：39
- XLSX：35
- JSON：32
- DOCX：12
- TXT：5
- DOC：2
- PPTX：1
- MP4：1

说明真实项目目录不是单纯源码仓库，而是同时包含：代码、需求、周报、进度表、标准文件、设计方案、接口清单、Skill、测试、演示数据、图片、输出物、临时脚本、历史交接包和 IDE/系统垃圾文件。

## 2. 主要目录

样本根目录可见：

```text
power_defect_agent_handoff/
├── backend/                         # 后端参考实现、tests、scripts
├── docs/                            # 架构、接口、验收、技术设计
├── power-defect-disposal-skill/     # 项目长期 Skill / references
├── data/                            # demo 数据和大量图片
├── outputs/                         # 生成的业务输出物
├── power_defect_agent_handoff_v2/   # 另一份交接包/重复版本
├── defect_image_exporter_release_v0.1.1/
├── .playwright-cli/                 # 浏览器自动化痕迹
├── .work_feature_list/              # 临时制表/截图工作目录
├── .idea/                           # IDE 文件
└── 大量根目录 docx/xlsx/md/png 等业务资料
```

根目录本身就有大量业务资料，因此 `project.yaml` 不能只支持固定 `docs/` 目录，必须支持 `*.docx`、`*.xlsx` 等 glob 声明。

对应示例配置：`examples/power-defect-agent.project.yaml`。

## 3. 这个样本暴露的关键问题

### 3.1 多版本资料非常普遍

例如同一项目中同时存在：

- 项目周报第4期 0814
- 项目周报第5期 0821
- 项目周报第6期 0828
- 项目周报第7期 0904

以及：

- `附件4：AI算法-需求功能清单V3_6.xlsx`
- `附件4：AI算法-需求功能清单V3_7.xlsx`
- `附件4：AI算法-需求功能清单V4_3.xlsx`

还有多个日期版本的 `生技域项目进度`。

因此平台不能把所有文件里的描述平铺后直接总结，否则旧口径会污染当前状态。

已增加中央 `project_memory.py`：

1. 识别文件名日期、V版本号、第N期；
2. 将明显属于同一系列的文件分组；
3. 当前视图只采用每组最新代表；
4. 旧版本仍保留在 historical 证据中，不删除；
5. API 返回 version families，便于审计为什么某个文件没有进入当前状态。

### 3.2 不能把“资料写了已完成”直接当成工程已完成

样本中同时存在：

- 周报/进度表：项目自述进展；
- `backend/`：代码实现；
- `backend/tests/`：测试证据；
- GitHub/GitLab：commit/branch/PR/CI 远端事实；
- `当前功能与原需求对应关系.xlsx`：需求与当前功能的人工映射。

后续 Evidence Fusion 必须按维度融合，而不是只信某一份 Word/Excel。

例如：

```text
周报：功能已完成
Git：存在对应修改
Test：通过
Push：未发生

=> 平台状态应为“本地开发完成/测试通过，尚未提交远端”，而不是简单“已完成”。
```

### 3.3 项目目录中有大量噪声

该样本包含：

- `__MACOSX`
- `.DS_Store`
- Office `.~` 临时文件
- `.idea`
- `.playwright-cli`
- `.work_feature_list`
- 大量 JPG/PNG/MP4
- 重复 handoff 包
- 与当前项目无关的低电压 Docker 替换包

所以扫描规则必须是“白名单项目路径 + ignore”，不能递归读取整个文件夹。

### 3.4 老式 `.doc` 仍然存在

样本中正式标准文件包含老式 `.doc`。当前 Document Intelligence 第一版支持 `.docx/.xlsx/文本`，因此 `.doc` 不能被静默忽略。

后续要求：

- 在 snapshot 中明确列出 `unsupported_critical_files`；
- 企业桌面版可选安装 LibreOffice/antiword 转换 `.doc`；
- 转换产物只放 Sentinel state volume，不改原项目文件；
- 正式标准原文必须保留来源路径和 hash。

### 3.5 PPT/图片不是第一阶段主进度来源

样本包含 PPTX、PNG、JPG、MP4。第一阶段不做全量视觉内容理解：

- PPTX 可后续增加文字/表格提取；
- PNG/JPG 默认只做元数据，除非项目显式配置为设计/验收证据；
- demo 图片集不进入项目进度 LLM；
- MP4 默认不读取正文。

## 4. 已识别的高价值进度资料

这份样本中，以下类型应该进入“当前项目状态”候选源：

- 最新项目周报；
- 最新生技域项目进度表；
- 项目整体进度情况；
- 当前功能与原需求对应关系；
- 最新会议纪要；
- 当前项目 Skill / references；
- backend 代码与 tests；
- 后续从 GitHub/GitLab 拉取的 branch/commit/PR/CI。

旧周报、旧需求功能清单和旧交接包仍作为历史来源保留，但默认不进入当前摘要。

## 5. 样本中可用于回归的当前事实示例

最新周报第7期（0904）里包含一组很典型的“进度 + 指标 + 问题 + 下一步”结构，例如：

- 1431 条缺陷样本全量验证；
- 完成定级 1019 条；
- 定级正确 883 条；
- 图像确认率 81.4%；
- 定级覆盖率 81.2%；
- 人工复核标签口径下已定级准确率 86.7%；
- 端到端准确率 81.7%；
- 当前仍需真实多模态模型回归、薄弱类别优化和正式生产接口确认。

这类内容非常适合验证 Document Intelligence 是否能正确抽取：

```text
progress
metrics
tests
blockers
next_steps
```

但这些资料事实仍需后续 Git/test/Agent 证据进行工程状态校验。

## 6. 下一步开发优先级

基于这个真实目录，后续顺序调整为：

1. 当前资料/历史资料分层（已开始）；
2. 强化 progress / metrics / blocker / next step 抽取；
3. 输出 unsupported/too-large/ignored 诊断清单，而不是只有统计数字；
4. Git changed files 语义分析；
5. GitHub/GitLab 远端证据接入；
6. Agent MCP 上报；
7. Evidence Fusion；
8. 项目总览/时间线页面。
