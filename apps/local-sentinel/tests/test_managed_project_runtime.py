from __future__ import annotations

import json

import local_control
import sentinel_runtime


def test_managed_project_binding_without_project_yaml_is_allowed(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    code = projects / "new-project" / "code"
    docs = projects / "shared-docs"
    code.mkdir(parents=True)
    docs.mkdir(parents=True)
    state = tmp_path / "state"
    state.mkdir()

    monkeypatch.setattr(local_control, "PROJECTS_ROOT", projects)
    monkeypatch.setattr(local_control, "STATE_ROOT", state)
    monkeypatch.setattr(local_control, "BINDINGS_PATH", state / "local-project-bindings.json")

    payload = local_control.FolderBindingSet(
        project_name="新业务项目",
        folders=[
            local_control.FolderBinding(path="new-project/code", role="code"),
            local_control.FolderBinding(path="shared-docs", role="documents"),
        ],
    )
    result = local_control.put_bindings("new-project", payload)
    assert result["saved"] is True
    assert result["project_name"] == "新业务项目"
    assert result["policy"]["security_mode"] == "metadata_only"
    stored = json.loads((state / "local-project-bindings.json").read_text(encoding="utf-8"))
    assert len(stored["projects"]["new-project"]["folders"]) == 2


def test_managed_manifest_stays_metadata_only_and_uses_selected_paths(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    code = projects / "code-a"
    docs = projects / "docs-a"
    code.mkdir(parents=True)
    docs.mkdir(parents=True)
    monkeypatch.setattr(sentinel_runtime.sentinel, "PROJECTS_ROOT", projects)

    manifest = sentinel_runtime.build_managed_manifest(
        "new-project",
        {
            "project_name": "新业务项目",
            "folders": [
                {"path": "code-a", "role": "code"},
                {"path": "docs-a", "role": "documents"},
            ],
        },
    )
    assert manifest["project"]["name"] == "新业务项目"
    assert manifest["paths"]["code"] == ["code-a"]
    assert manifest["paths"]["documents"] == ["docs-a"]
    assert manifest["security"]["mode"] == "metadata_only"
    assert manifest["analysis"]["enabled"] is False


def test_managed_manifest_can_enable_local_document_analysis_without_source_upload(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    docs = projects / "docs-a"
    docs.mkdir(parents=True)
    monkeypatch.setattr(sentinel_runtime.sentinel, "PROJECTS_ROOT", projects)

    manifest = sentinel_runtime.build_managed_manifest(
        "new-project",
        {
            "project_name": "新业务项目",
            "folders": [{"path": "docs-a", "role": "documents"}],
            "policy": {
                "enabled": True,
                "security_mode": "local_analysis",
                "analysis_enabled": True,
                "use_llm": True,
                "include": ["documents"],
            },
        },
    )
    assert manifest["security"]["mode"] == "local_analysis"
    assert manifest["security"]["upload_source_code"] is False
    assert manifest["security"]["upload_documents"] is False
    assert manifest["analysis"]["enabled"] is True
    assert manifest["analysis"]["use_llm"] is True
    assert manifest["analysis"]["include"] == ["documents"]


def test_scan_once_emits_managed_project_without_manifest(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    selected = projects / "new-project"
    selected.mkdir(parents=True)
    monkeypatch.setattr(sentinel_runtime.sentinel, "PROJECTS_ROOT", projects)
    monkeypatch.setattr(sentinel_runtime.sentinel, "discover_projects", lambda: [])
    monkeypatch.setattr(
        sentinel_runtime,
        "load_bindings",
        lambda: {
            "version": 1,
            "projects": {
                "new-project": {
                    "project_name": "新业务项目",
                    "folders": [{"path": "new-project", "role": "documents"}],
                }
            },
        },
    )
    monkeypatch.setattr(
        sentinel_runtime.sentinel,
        "build_snapshot",
        lambda root, manifest: {
            "project_id": manifest["project"]["id"],
            "project_name": manifest["project"]["name"],
            "workspace_name": root.name,
        },
    )
    captured = []
    monkeypatch.setattr(sentinel_runtime.sentinel, "upload_snapshot", lambda snapshot: captured.append(snapshot) or True)
    monkeypatch.setattr(sentinel_runtime.sentinel, "utc_now", lambda: "2026-09-11T00:00:00Z")

    result = sentinel_runtime.scan_once("new-project")
    assert result["matched"] == 1
    assert result["uploaded"] == 1
    assert captured[0]["project_id"] == "new-project"
    assert captured[0]["workspace_name"] == "configured:new-project"
    assert captured[0]["local_binding_overlay"]["managed_without_manifest"] is True


def test_disabled_project_is_not_scanned(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    selected = projects / "new-project"
    selected.mkdir(parents=True)
    monkeypatch.setattr(sentinel_runtime.sentinel, "PROJECTS_ROOT", projects)
    monkeypatch.setattr(sentinel_runtime.sentinel, "discover_projects", lambda: [])
    monkeypatch.setattr(
        sentinel_runtime,
        "load_bindings",
        lambda: {
            "version": 1,
            "projects": {
                "new-project": {
                    "project_name": "新业务项目",
                    "folders": [{"path": "new-project", "role": "documents"}],
                    "policy": {
                        "enabled": False,
                        "security_mode": "metadata_only",
                        "analysis_enabled": False,
                        "use_llm": False,
                        "include": ["documents"],
                    },
                }
            },
        },
    )
    monkeypatch.setattr(sentinel_runtime.sentinel, "upload_snapshot", lambda snapshot: (_ for _ in ()).throw(AssertionError("should not upload")))
    monkeypatch.setattr(sentinel_runtime.sentinel, "utc_now", lambda: "2026-09-11T00:00:00Z")

    result = sentinel_runtime.scan_once("new-project")
    assert result["matched"] == 0
    assert result["uploaded"] == 0
    assert result["skipped_disabled"] == 1
