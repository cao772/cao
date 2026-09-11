# 平台配置层设计

## 目标

在现有研发协同管理 Dashboard 之上增加独立的“平台配置”入口，把当前依赖 YAML / Docker 环境变量的接入方式逐步业务化：

- 前端配置 GitLab 地址与 Token；
- 测试 GitLab 连接并检索当前 Token 可访问的全部项目；
- 将一个业务项目绑定一个或多个 GitLab 仓库；
- 在开发人员本机选择一个或多个本地目录作为该业务项目的采集范围；
- 配置资料、代码、测试、输出目录的扫描范围；
- 保留现有 `project.yaml` / `config/gitlab-projects.yaml` 兼容能力，不一次性推翻现有链路。

核心原则仍不变：中央采集远端事实，本机 Sentinel 采集只有本机才能看到的现场；Token、源码、业务文档不因增加配置页面而扩大暴露范围。

## 前端信息架构

左侧导航增加独立区域：

```text
项目
  - 缺陷处置
  - 低电压
  - HyClaw

平台配置
  - GitLab 接入
  - 项目接入与绑定
  - 本机采集
```

### GitLab 接入

字段：

- GitLab 地址，默认 `http://git.hyetec.com`
- Personal Access Token，密码框，不回显原文
- 连接状态
- 最近验证时间
- “测试连接”
- “保存并检索项目”

Token 不写浏览器 localStorage，不写公开仓库，不通过 GET API 返回明文。

### GitLab 项目检索

连接成功后调用 GitLab `/api/v4/projects` 分页检索 Token 可见项目，表格至少展示：

- 项目名称
- namespace / path_with_namespace
- 项目 ID
- 默认分支
- 最近活动时间
- Web 地址
- 已绑定到哪个业务项目

支持名称 / namespace 搜索、分页和多选。

注意：不能把“一个 GitLab 项目”等同于“一个业务项目”。例如低电压业务项目仍应允许同时绑定 `algorithm` 与 `voltage-management` 两个仓库。

### 项目接入与绑定

业务对象关系：

```text
业务项目 Project
  ├── 0..N GitLab Repository
  ├── 0..N Local Folder Binding
  ├── 0..N Developer / Device
  └── 0..N Coding Agent
```

可从已有业务项目中选择，也可以新建一个平台项目，然后给它绑定多个 GitLab 仓库。

### 本机采集

本机目录不能由中央服务器直接遍历。增加仅绑定 loopback 的 Local Control 服务：

```text
http://127.0.0.1:6411
```

浏览器打开中央 Dashboard 时，由浏览器直接访问本机 `6411`，因此未来每个开发人员都可以在自己的电脑上选择自己的目录，而不要求中央服务器访问员工磁盘。

Local Control 只允许查看 Docker 已挂载到 `/projects` 的目录；不能突破 Docker volume 边界读取任意宿主机目录。

第一版页面展示：

- 当前本机用户 / device_id
- Sentinel 在线状态
- Docker 当前可见根目录
- 本地项目 / 文件夹树
- 多选目录
- 每个目录指定用途：`代码` / `项目资料` / `测试` / `输出`
- 保存采集范围
- 立即重新采集

保存后的配置进入 Sentinel 自己的 state volume，例如：

```json
{
  "version": 1,
  "projects": {
    "low-voltage": {
      "folders": [
        {"path": "low-voltage/algorithm-ryj", "role": "code"},
        {"path": "low-voltage/voltage-management", "role": "code"},
        {"path": "low-voltage/project-files", "role": "documents"},
        {"path": "low-voltage/test-results", "role": "tests"}
      ]
    }
  }
}
```

不直接修改用户业务目录里的 `project.yaml`。运行时按“平台本机覆盖配置 > project.yaml > 默认值”合并扫描范围。

## Docker 边界

当前 `deployments/local/docker-compose.yml` 只有一个：

```yaml
${PROJECTS_PATH}:/projects:ro
```

因此第一版“选择多个文件夹”指 `/projects` 已挂载根目录下的多个目录。

如果目录不在当前 `PROJECTS_PATH` 下，UI 应明确提示：该目录尚未授权给 Docker，需要先调整本机采集根目录后重启本地栈；不能为了方便把整个 `/Users` 或磁盘根目录默认挂进去。

后续可以增加多根目录 Compose override 生成器，但不属于第一版。

## 中央数据模型

在现有 SQLite MVP 中增加独立配置表，避免把配置混进 snapshots：

```text
source_connections
- id
- provider
- base_url
- token_ciphertext
- token_hint
- enabled
- verified_at
- updated_at

project_repository_bindings
- project_id
- provider
- remote_project_id
- path_with_namespace
- repository_url
- role
- enabled
- updated_at

local_folder_bindings
- project_id
- user_id
- device_id
- local_path
- role
- enabled
- updated_at
```

后续迁移 PostgreSQL 时保持相同领域模型。

## Token 保存

推荐中央 API 使用持久化数据卷中的平台密钥对 Token 加密后保存：

```text
/data/platform.key
/data/project.db
```

- `platform.key` 首次启动生成，权限限制为仅服务进程可读；
- DB 只保存密文与末尾 4 位提示；
- GET 只返回 `configured=true` 与 `token_hint`；
- 前端密码框刷新后保持空白；
- 日志、异常、测试输出不得打印 Token。

## API 设计

中央 API：

```text
GET  /api/v1/platform/gitlab
PUT  /api/v1/platform/gitlab
POST /api/v1/platform/gitlab/test
POST /api/v1/platform/gitlab/discover

GET  /api/v1/platform/project-bindings
PUT  /api/v1/platform/projects/{project_id}/repositories

GET  /api/v1/platform/devices
GET  /api/v1/platform/projects/{project_id}/local-bindings
```

Local Control（127.0.0.1:6411）：

```text
GET  /health
GET  /api/v1/local/info
GET  /api/v1/local/folders?depth=3
GET  /api/v1/local/bindings
PUT  /api/v1/local/projects/{project_id}/bindings
POST /api/v1/local/projects/{project_id}/scan
```

所有 path 必须转成 `/projects` 下的相对路径并做 resolve/relative_to 校验，拒绝 `../` 逃逸。

## GitLab Collector 动态配置

现在 Collector 读取：

- `GITLAB_TOKEN`
- `config/gitlab-projects.yaml`

平台配置上线后改成：

1. 中央配置层为主；
2. `gitlab-projects.yaml` 继续作为 bootstrap / fallback；
3. Collector 每轮从中央内部接口读取已启用连接和仓库绑定；
4. 不需要用户每次改 YAML、改 `.env`、重建容器才能新增仓库。

内部接口必须使用 `X-Collector-Token`，不暴露给普通前端。

## 实现顺序

### Phase A：配置页面 + GitLab 动态发现

先完成 GitLab Token、测试连接、检索全部项目、保存仓库绑定。此阶段不改 Sentinel 扫描语义。

### Phase B：Local Control + 多目录选择

增加本机 `6411` 服务、目录树、多选、role、state override、立即重新采集。

### Phase C：Collector 动态注册表

把静态 `gitlab-projects.yaml` 降级为兼容入口，Collector 改读中央已保存仓库绑定。

### Phase D：完善平台管理

再增加：设备在线状态、Agent 配置、采集周期、LLM 配置、权限与审计。

## 第一版验收

1. 前端左侧能进入“平台配置”，不混在某个具体项目 Dashboard 中。
2. Token 输入后可测试 GitLab，成功时显示当前 GitLab 用户但不显示 Token。
3. 可以拉出当前 Token 可访问的完整项目列表并搜索。
4. 可以把两个 GitLab 仓库绑定到同一个“低电压”业务项目。
5. 本机页面只能看到 Docker 已授权目录，不能越权浏览宿主机其它目录。
6. 可以给“低电压”同时选择多个本地目录，并保存 code/documents/tests/outputs 角色。
7. 保存后 Sentinel 下一轮 Snapshot 的扫描范围真实变化，而不是只改前端显示。
8. 现有三个项目、Evidence Fusion、周度进展、人员协作不回归。
9. Token 不出现在 Git、浏览器存储、GET 响应、日志、截图中。
