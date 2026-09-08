# project.yaml 规范

每个受管项目根目录必须包含 `project.yaml`。Sentinel 只注册包含该文件的目录，避免误扫个人文件夹。

一个业务项目可以对应 **一个或多个 Git 仓库**。例如低电压项目同时包含前端 `voltage-management.git` 和算法 `algorithm.git`，中央仍然只显示一个“低电压项目”，任务证据在项目级融合。

## 单仓库项目

旧版 `repository:` 继续兼容：

```yaml
version: 1
project:
  id: power-defect-agent
  name: 基于多模态大模型及智能体的电力设备缺陷处置
  owner: caoyh
  team: ai-project

repository:
  id: multimodal-agent
  role: application
  provider: gitlab
  url: http://git.hyetec.com/hyetec/rj26nw025/multimodal-agent.git
  local_path: .
  default_branch: cyh
```

## 多仓库项目

推荐使用 `repositories:`：

```yaml
version: 1
project:
  id: low-voltage
  name: 低电压精准立项资料审核智能体
  owner: caoyh
  team: ai-project

repositories:
  - id: low-voltage-algorithm
    role: algorithm
    provider: gitlab
    url: http://git.hyetec.com/hyetec/rj26nw011/algorithm.git
    local_path: algorithm-ryj
    default_branch: ryj
    primary: true

  - id: low-voltage-frontend
    role: frontend
    provider: gitlab
    url: http://git.hyetec.com/hyetec/rj26nw011/Front-end/voltage-management.git
    local_path: voltage-management
    default_branch: main
    primary: false
```

### repository 字段

- `id`：仓库在项目内的稳定 ID，建议使用业务可读名称；
- `role`：`frontend`、`algorithm`、`backend`、`plugins`、`application` 等逻辑职责；
- `provider`：`gitlab` / `github` / `gitea` / `other`；
- `url`：远端仓库 URL；
- `local_path`：相对项目根目录的本地 clone 路径；
- `primary`：只用于兼容旧页面的 branch/head 展示；项目 `dirty/ahead/changed_files` 仍聚合所有仓库；
- `default_branch` / `development_branches`：远端与开发分支元数据。

`local_path` 不允许通过 `../` 逃出受管项目目录。

## 资料路径

```yaml
paths:
  code:
    - algorithm-ryj
    - voltage-management
  documents:
    - '*.docx'
    - '*.xlsx'
    - docs
  tests:
    - '*测试*.xlsx'
    - tests
  outputs:
    - output
    - reports
```

历史项目不要求重构目录，只需要用 `paths` 描述现有结构。

## 忽略规则

```yaml
ignore:
  - node_modules
  - .venv
  - dist
  - build
  - __pycache__
  - '*.zip'
  - '*.7z'
  - '~$*'
```

`ignore` 优先级最高。历史副本、压缩归档和其他项目资料应显式排除，防止旧版本污染当前项目状态。

## security.mode

```yaml
security:
  mode: metadata_only
  upload_source_code: false
  upload_documents: false
```

- `metadata_only`：只采集路径、类型、大小、时间、hash、Git/测试统计；不读取文件正文。
- `local_analysis`：允许本机解析 manifest 白名单内容；中央只收到结构化摘要。
- `central_analysis`：允许将明确允许的文本片段发送中央分析；必须显式配置。

无论 manifest 怎样配置，`.env`、密钥、证书和凭证目录仍受硬安全规则保护。

## Progress sources

```yaml
progress:
  sources:
    - git
    - tests
    - local_workspace
    - tasks
    - agent
    - ci
```

正式进度不能由 LLM 从代码量或聊天内容猜测。任务状态来源于证据：项目资料、本地 Git、测试、Agent、远端 Commit/MR/CI/Deployment。

## 项目身份

`project.id` 在一个组织内唯一且稳定，不使用本地文件夹名或仓库名作为唯一项目主键。

中央关系：

```text
project.id
  ├─ repository A
  ├─ repository B
  ├─ user/device/workspace A
  ├─ user/device/workspace B
  └─ task/evidence
```

因此一个开发人员可以在不同设备开发同一项目，不同开发人员也可以分别修改前端/算法仓库，最终仍聚合到同一任务与项目状态。
