# Document Intelligence Pipeline

## 目标

Local Sentinel 不把项目目录全文上传中央，而是在开发人员本机对明确授权的项目资料做增量解析，形成结构化项目事实，再随项目快照上报。

第一版支持：

- 文本/代码：`.md .txt .rst .json .yaml .yml .py .js .jsx .ts .tsx .java .go .rs .c .h .cpp .hpp .sh .sql`
- Word：`.docx`
- Excel：`.xlsx`

暂不做：

- PDF OCR
- PPT
- 二进制附件内容分析
- 自动修改项目文件

## 启用条件

正文分析必须同时满足：

1. `project.yaml` 中 `security.mode: local_analysis`
2. `analysis.enabled` 未关闭
3. 文件位于 `analysis.include` 对应的 `paths.*` 白名单范围
4. 文件不是敏感路径/敏感后缀，且没有命中 `ignore`
5. 文件大小不超过 `analysis.max_file_bytes`

`metadata_only` 模式永远不读取正文。

## 增量链路

```text
project.yaml
    ↓
发现白名单文件
    ↓
路径 / 大小 / hash
    ↓
本地 SQLite 查询 hash
    ├─ 未变化 → 直接复用上次结构化结果
    └─ 新增/变化
          ↓
       格式解析器
          ↓
       文档角色分类
          ↓
  规则抽取 / 可选本机 LLM
          ↓
       结构化事实
          ↓
      Project Memory
          ↓
   Snapshot.analysis
```

每个项目的分析缓存位于 Sentinel 独立 Docker volume `/state/<project_id>.sqlite3`，不写入项目目录。

## Word / Excel 处理

Word 使用 `python-docx` 提取段落和表格。

Excel 使用 `openpyxl` 的只读模式，只抽取每个 sheet 的有限行列作为语义样本，默认每个 sheet 最多 200 行、30 列，避免大表被整表送入模型。

## 文档角色

会根据声明目录与文件名先做预分类：

- requirement
- test_result
- handoff
- report
- design
- interface
- deployment
- decision
- code
- document/output

角色只是索引标签，不直接等同于项目进度结论。

## 结构化事实

每个文件分析结果只保留：

- `summary`
- `document_role`
- `facts`
- `mentioned_modules`
- parser 元数据
- path / hash

`facts.type` 目前支持：

- requirement
- decision
- task
- test
- blocker
- milestone
- deployment
- note

中央不会收到本次解析使用的原始正文。

## 可选本机 LLM

默认 `analysis.use_llm: false`，使用确定性关键词抽取。

需要本机模型时：

```yaml
security:
  mode: local_analysis

analysis:
  use_llm: true
```

Docker 环境变量示例：

```bash
export LOCAL_LLM_BASE_URL='http://host.docker.internal:11434/v1'
export LOCAL_LLM_MODEL='qwen3:8b'
```

接口按 OpenAI-compatible `/chat/completions` 调用。

默认只允许 localhost、127.0.0.1、`host.docker.internal` 等本机地址。若确实需要把项目内容发送到远端模型，必须显式设置：

```bash
ALLOW_REMOTE_ANALYSIS_ENDPOINT=true
```

这一步是有意设置的安全门。

## 当前边界

第一版的 `Project Memory` 是文件事实聚合，不负责自行估算“项目完成 80%”。

后续 Evidence Fusion 会把：

- 本地资料事实
- Git 状态
- Agent 上报
- 测试结果
- GitHub/GitLab commit / PR / CI

关联后再判断“开发中 / 待提交 / 待测试 / 已交付 / 阻塞”等证据状态。
