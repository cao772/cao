from __future__ import annotations

import main as main_module
from main import (
    app,
    latest_workspace_snapshots,
    project_evidence,
    recent_agent_events,
    recent_remote_events,
)
from agent_api import router as agent_router
from model_config import router as model_config_router
from node_status import router as node_status_router
from people_identity import router as people_identity_router
from people_store import resolve_contributors
from platform_config import router as platform_router
from project_brief import build_project_brief
from project_settings import router as project_settings_router


_raw_project_rollup = main_module.project_rollup


def _people_aware_project_rollup(project_id: str) -> dict:
    rollup = _raw_project_rollup(project_id)
    contributors = resolve_contributors(list(rollup.get("contributors") or []))
    resolved = dict(rollup)
    resolved["contributors"] = contributors
    resolved["contributor_count"] = len(contributors)
    resolved["local_contributor_count"] = sum(
        1 for item in contributors if "local" in (item.get("source_types") or [])
    )
    resolved["repository_contributor_count"] = sum(
        1 for item in contributors if "repository" in (item.get("source_types") or [])
    )
    return resolved


# Keep main.py routes backward compatible while letting their runtime global lookup use
# the people projection in the production business app.
main_module.project_rollup = _people_aware_project_rollup

app.include_router(platform_router)
app.include_router(project_settings_router)
app.include_router(model_config_router)
app.include_router(node_status_router)
app.include_router(people_identity_router)
app.include_router(agent_router)


@app.get("/api/v1/projects/{project_id}/brief")
def get_project_brief(project_id: str) -> dict:
    snapshots = latest_workspace_snapshots(project_id)
    fusion = project_evidence(project_id)
    remote_events = recent_remote_events(project_id, 2000)
    agent_events = recent_agent_events(project_id, 500)
    brief = build_project_brief(
        snapshots,
        fusion,
        remote_events,
        agent_events,
    )
    brief["project_id"] = project_id
    return brief
