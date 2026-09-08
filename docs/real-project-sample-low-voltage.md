# 真实项目样本：低电压 algorithm版本管理

来源：用户提供的 Finder 截图。该目录不是一个干净的 Git 仓库根目录，而是一个真实的“项目资料 + 版本管理 + 代码副本 + 交接包”工作区。

## 截图可见的典型内容

### 测试 / 开发任务

- `6_4 上线版本测试表.xlsx`
- `6_11 上线版本测试表.xlsx`
- `6.18 工作任务对应测试表.xlsx`
- `6.22-6.26 任务测试.xlsx`
- `6.30-7.9 开发任务_测试表.xlsx`
- `6.30-7.9 开发任务.xlsx`
- `7.2 工作任务.xlsx`
- `7.3 任务.xlsx`
- `7.7 工作任务.xlsx`
- `629-7.9 任务测试.xlsx`

### 需求 / 问题 / 项目资料

- `2026年低电压项目清单.csv`
- `260625发-修理智能评审定额套用错误.xlsx`
- `低电压_定额套用错误填报需求开发拆解表.xlsx`
- `低电压精准治理项目主要设备材料清单 6_17(2).xlsx`
- `低电压项目 8.12问题反馈表.xlsx`
- `低电压自动化上传规范.xlsx`
- `未来发展规划相关问题及建议.docx`
- `一般低电压台区通过项目明细表 2026_6_17.xlsx`
- `南方电网定额【2026】6号…主要设备材料信息价.pdf`

### 代码 / 版本副本

- `algorithm-ryj/`
- `algorithm-ryj 5/`
- `algorithm-ryj 7_副本/`
- `algorithm-ryj 7_副本.zip`
- `api_servers.py`

### 交接 / 压缩归档

- `alignment_handoff_pack/`
- `alignment_handoff_pack.zip`
- `clean_json_generation_handoff_pack/`
- `clean_json_generation_handoff_pack.zip`
- `低电压治理_RemoteMCP.tar.gz`

### 跨项目污染

截图中同时存在：

- `金仲铂新需求/`
- `生产项目四虚风险智能研判需求整理表.xlsx`

这两项属于另一个“生产项目四虚风险智能研判”项目，不能自动并入低电压项目当前状态。

## 对平台设计的直接影响

### 1. 项目根目录不等于 Git 根目录

原设计只检查 `<project>/.git`，在这种工作区会错误判断“不是 Git 项目”。

现在增加：

```yaml
repository:
  local_path: algorithm-ryj
```

Sentinel 以项目根目录管理资料，但以 `repository.local_path` 作为当前代码仓的 Git 证据来源。

### 2. 不能扫描所有同名代码目录

`algorithm-ryj 5`、`algorithm-ryj 7_副本` 属于旧副本或阶段副本。当前 Git 状态只锚定 manifest 声明的 canonical repo，其他副本不能因为修改时间更晚就替代当前代码仓。

### 3. 项目资料需要白名单 + 排除规则

根目录存在大量 Excel/Word/PDF，适合使用：

```yaml
paths:
  documents:
    - '*.xlsx'
    - '*.csv'
    - '*.docx'
    - '*.pdf'
```

同时通过 `ignore` 排除跨项目资料、压缩包和明确副本。

### 4. 压缩包不能重复当证据

目录与对应 ZIP 并存时，例如：

```text
alignment_handoff_pack/
alignment_handoff_pack.zip
```

压缩包是交付形态，不应再次独立计入需求/代码/进度证据。第一版通过 manifest 排除归档包；中央 Workspace Inventory 也增加了目录+压缩包重复诊断能力。

### 5. 需要区分“能索引”与“能读正文”

当前正文解析支持：

- Markdown / TXT / JSON / YAML / 常见源码文本
- DOCX
- XLSX

当前只做元数据、尚未正式接正文解析的格式包括：

- CSV
- PDF
- PPTX
- 旧版 DOC

这些文件不能静默消失。中央 `workspace_inventory` 会显式列出 `pending_parsers`，后续逐步补 parser。

## 推荐放置方式

本地最终建议：

```text
~/company-projects/
└── 低电压项目/
    ├── project.yaml              # 使用 examples/low-voltage-algorithm-version.project.yaml
    ├── algorithm-ryj/            # canonical Git repo
    ├── algorithm-ryj 5/          # 历史副本
    ├── algorithm-ryj 7_副本/      # 历史副本
    ├── 各类测试/需求/问题反馈.xlsx
    ├── 标准/规划.docx/pdf
    └── 交接包与归档文件
```

不要求用户重构历史目录，只要求 `project.yaml` 明确：

- 当前 Git repo 在哪里；
- 哪些资料属于项目；
- 哪些是历史/副本/压缩归档；
- 哪些是其他项目资料；
- 是否允许本机正文分析。

## 下一步验证目标

1. 把该真实目录复制/移动到 Sentinel 的受管项目根目录下；
2. 放入示例 `project.yaml` 并按实际 Git 地址/分支调整；
3. 启动本地 Docker Sentinel；
4. 验证 `git.repository_path = algorithm-ryj`；
5. 验证根目录测试表/需求表被解析；
6. 验证四虚资料、旧副本和压缩包不进入当前项目状态；
7. 继续补 CSV/PDF/DOC/PPTX parser 与 Git changed-files 语义分析。
