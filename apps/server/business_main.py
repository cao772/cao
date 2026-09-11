from __future__ import annotations

import main as main_module
from main import app
from agent_api import router as agent_router
from model_config import router as model_config_router
from node_status import router as node_status_router
from people_identity import router as people_identity_router
from people_store import resolve_contributors
from platform_config import router as platform_router
from project_settings import router as project_settings_router


_raw_project_rollup = main_module.project_rollup
_raw_project_brief = main_module.project_brief


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


def _business_project_brief(project_id: str) -> dict:
    """Preserve main.py's registered route while enriching its runtime result."""
    brief = dict(_raw_project_brief(project_id))
    brief["project_id"] = project_id
    return brief


# main.py registers these routes before business_main adds the production routers.
# Patch the runtime functions those existing handlers look up instead of registering
# duplicate FastAPI paths, which would leave the later handler unreachable.
main_module.project_rollup = _people_aware_project_rollup
main_module.project_brief = _business_project_brief

app.include_router(platform_router)
app.include_router(project_settings_router)
app.include_router(model_config_router)
app.include_router(node_status_router)
app.include_router(people_identity_router)
app.include_router(agent_router)
