from __future__ import annotations

import subprocess
import sys


def test_business_main_keeps_single_project_brief_route():
    script = r'''
import business_main

path = "/api/v1/projects/{project_id}/brief"
routes = [route for route in business_main.app.routes if getattr(route, "path", None) == path]
assert len(routes) == 1, [(getattr(route, "path", None), getattr(route, "name", None)) for route in routes]

business_main._raw_project_brief = lambda project_id: {"stage": "integration-review"}
brief = business_main._business_project_brief("demo")
assert brief == {"stage": "integration-review", "project_id": "demo"}
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_business_main_registers_project_intelligence_routes():
    script = r'''
import business_main

paths = {getattr(route, "path", None) for route in business_main.app.routes}
assert "/api/v1/projects/{project_id}/intelligence" in paths
assert "/api/v1/projects/{project_id}/search" in paths
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_business_main_registers_conversation_intelligence_routes():
    script = r'''
import business_main

paths = {getattr(route, "path", None) for route in business_main.app.routes}
assert "/api/v1/conversation-events" in paths
assert "/api/v1/projects/{project_id}/communications/search" in paths
assert "/api/v1/projects/{project_id}/communications/summary" in paths
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_production_routes_are_unique_and_include_integrated_capabilities():
    script = r'''
from collections import Counter
import business_main
pairs = [(method, route.path) for route in business_main.app.routes for method in getattr(route, "methods", set())]
assert not [key for key, count in Counter(pairs).items() if count > 1]
paths = business_main.app.openapi()["paths"]
for path in ["/api/v1/projects", "/api/v1/projects/{project_id}/brief", "/api/v1/projects/{project_id}/intelligence", "/api/v1/search", "/api/v1/projects/{project_id}/communications/search", "/api/v1/projects/{project_id}/communications/summary", "/api/v1/industry-news"]:
    assert "get" in paths[path], path
'''
    result = subprocess.run([sys.executable, "-c", script], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or result.stdout
