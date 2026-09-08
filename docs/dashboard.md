# 项目管理驾驶舱

中央 `docker-compose` 现在默认启动 Web Dashboard：

```text
http://<central-host>:8088
```

可通过 `WEB_PORT` 修改宿主机端口。

## 页面结构

左侧项目列表：
- 项目名称；
- 当前项目状态；
- 开发人员数量。

项目详情：
- 项目状态、人员、任务、本地未提交、远端事件等指标；
- 任务与证据状态；
- Project Memory 当前阶段、进行中、阻塞、下一步；
- 人员与 Coding Agent；
- 本地 Snapshot、Agent Event、GitLab/GitHub Remote Event 汇总时间线。

## 数据来源

Dashboard 本身不重新分析项目，只读取中央 API：

```text
/api/v1/projects
/api/v1/projects/{project_id}/current
/api/v1/projects/{project_id}/tasks
/api/v1/projects/{project_id}/contributors
/api/v1/projects/{project_id}/agent-events
/api/v1/projects/{project_id}/remote-events
/api/v1/projects/{project_id}/snapshots
```

Nginx 在同一容器入口下把 `/api/*` 反向代理到 `server:8080`，因此浏览器不需要跨域访问中央 API。

## 启动

```bash
export COLLECTOR_TOKEN='replace-with-a-random-token'
export WEB_PORT='8088'

docker compose -f deployments/central/docker-compose.yml up --build -d
```

然后打开：

```text
http://localhost:8088
```

如果还没有任何 Sentinel 上报，页面会显示“暂无项目”，不会制造示例项目数据。
