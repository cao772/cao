# GitLab Remote Collector

## 目标

GitLab 远端数据由中央 Collector 统一采集，不让每个开发人员的 Docker Desktop 重复请求同一批仓库。

当前真实 GitLab：

```text
http://git.hyetec.com
```

仓库登记见 `config/gitlab-projects.yaml`。

## 权限

建议为 Collector 创建专用只读账号/Token，优先使用能读取以下 API 的最小权限：

- Project metadata；
- Repository commits；
- Merge Requests；
- Pipelines；
- Deployments（项目启用时）。

通常 GitLab Personal/Project Access Token 的 `read_api` 是第一选择；具体以公司 GitLab 版本和权限策略为准。不要使用个人高权限 Token 作为长期生产配置。

Token 不允许提交到 Git 仓库、`project.yaml` 或 `config/gitlab-projects.yaml`。

## 公司网络内先做连通性验证

```bash
export GITLAB_BASE_URL='http://git.hyetec.com'
export GITLAB_TOKEN='***'

curl -sS \
  -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
  "${GITLAB_BASE_URL}/api/v4/projects/hyetec%2Frj26nw011%2Falgorithm"
```

如果成功，应返回该 GitLab Project 的 JSON 元数据。

四个实际 project path：

```text
hyetec/rj26nw011/Front-end/voltage-management
hyetec/rj26nw011/algorithm
hyetec/rj26nw025/multimodal-agent
hyetec/rrj26rj001/hyclaw/plugins/hyclaw-plugins
```

注意 URL 中 `/` 需要百分号编码成 `%2F`。

## Docker 启动

先启动中央 API：

```bash
export COLLECTOR_TOKEN='random-internal-token'
docker compose -f deployments/central/docker-compose.yml up --build -d
```

再启用 GitLab profile：

```bash
export GITLAB_BASE_URL='http://git.hyetec.com'
export GITLAB_TOKEN='***'

docker compose \
  -f deployments/central/docker-compose.yml \
  --profile gitlab \
  up --build -d
```

查看 Collector：

```bash
docker compose \
  -f deployments/central/docker-compose.yml \
  --profile gitlab \
  logs -f gitlab-collector
```

## 中央 API 验证

低电压项目：

```bash
curl http://localhost:8080/api/v1/projects/low-voltage/remote-events
curl http://localhost:8080/api/v1/projects/low-voltage/tasks
curl http://localhost:8080/api/v1/projects/low-voltage/evidence
```

预期远端事件包含 `repository_id`，例如：

```text
low-voltage-frontend
low-voltage-algorithm
```

两者仍属于同一个 `project_id=low-voltage`。

## 采集周期

默认：

```text
300 秒 / 5 分钟
```

可调整：

```bash
export GITLAB_POLL_INTERVAL_SECONDS=120
```

第一轮默认回看 24 小时：

```bash
export GITLAB_INITIAL_LOOKBACK_HOURS=72
```

Collector 在自己的 Docker volume 中记录每个 repository 的上次成功采集时间，并保留 2 分钟重叠窗口。中央使用 `client_event_id` 幂等去重，所以重叠不会重复计数。

## 事件模型

```text
GitLab Commit      -> git.commit
Merge Request open -> merge_request.opened
Merge Request merge-> merge_request.merged
Pipeline success   -> ci.passed
Pipeline failed    -> ci.failed
Deployment success -> deployment.succeeded
Deployment failed  -> deployment.failed
```

## 任务关联

优先顺序：

1. 明确 `task_id`；
2. MR 标题 / Commit message 与任务语义匹配；
3. 已关联远端事件建立 `repository + commit SHA / branch` 映射；
4. Pipeline/Deployment 根据同仓库 SHA/ref 继承任务。

因此并不要求每一个 Pipeline 都写业务任务名。

## 当前边界

- CI 环境无法访问公司私有 `git.hyetec.com`，所以仓库真实连通/权限必须在公司网络实测；
- 当前先采用定时 API 采集，后续补 GitLab Webhook 和 Apache DevLake adapter；
- 如果公司 GitLab 版本不支持某个 Deployment filter，Collector 会记录 warning，但不会影响 Commit/MR/Pipeline 采集；
- 真实生产建议将 Token 放 Docker Secret / Kubernetes Secret / Vault，而不是 shell history。
