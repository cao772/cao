# project.yaml 规范

每个受管项目根目录必须包含 `project.yaml`。Sentinel 只注册包含该文件的目录，避免误扫个人文件夹。

## 必填字段

```yaml
version: 1
project:
  id: low-voltage
  name: 低电压精准立项资料审核智能体
  owner: caoyh
  team: ai-project

repository:
  provider: github
  url: https://github.com/example/low-voltage.git
  default_branch: main

paths:
  code:
    - app
    - frontend
  documents:
    - docs
    - requirements
  tests:
    - tests
  outputs:
    - output
    - reports

ignore:
  - node_modules
  - .venv
  - dist
  - build
  - __pycache__
  - '*.zip'
  - '*.7z'

security:
  mode: metadata_only
  upload_source_code: false
  upload_documents: false

progress:
  sources:
    - git
    - tests
    - local_workspace
    - tasks
```

## security.mode

- `metadata_only`：只采集路径、类型、大小、时间、hash、Git/测试统计；不读取文件正文。
- `local_analysis`：允许本机模型读取 manifest 允许的内容，中央只收到结构化摘要。
- `central_analysis`：允许将明确允许的文本片段发送中央分析；必须显式配置。

## 路径规则

1. 未声明的目录默认不做内容分析。
2. `ignore` 优先级最高。
3. `.env`、密钥文件、凭证目录默认拒绝读取正文，即使误写入 `documents`。
4. 源码默认只做 Git 与文件元数据采集，不上传全文。
5. 历史项目不要求重构目录，只需要用 `paths` 描述现有结构。

## 项目身份

`project.id` 在一个组织内唯一且稳定，不使用本地文件夹名作为唯一主键。中央平台通过 `project.id + user/device/workspace` 关联多名开发者的同一项目。
