from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

import local_control
import sentinel_runtime


def test_binding_path_must_stay_inside_authorized_root(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    allowed = root / "demo" / "docs"
    allowed.mkdir(parents=True)
    monkeypatch.setattr(local_control, "PROJECTS_ROOT", root)
    assert local_control.resolve_authorized_folder("demo/docs") == allowed.resolve()
    with pytest.raises(HTTPException):
        local_control.resolve_authorized_folder("../outside")


def test_symlink_escape_is_rejected(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    outside = tmp_path / "secret"
    outside.mkdir()
    link = root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink unavailable")
    monkeypatch.setattr(local_control, "PROJECTS_ROOT", root)
    with pytest.raises(HTTPException):
        local_control.resolve_authorized_folder("escape")


def test_runtime_bindings_override_selected_path_roles(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    root = projects / "low-voltage"
    algorithm = root / "algorithm"
    algorithm.mkdir(parents=True)
    (algorithm / ".git").mkdir()
    (root / "资料").mkdir()
    monkeypatch.setattr(sentinel_runtime.sentinel, "PROJECTS_ROOT", projects)
    manifest = {
        "version": 1,
        "project": {"id": "low-voltage", "name": "低电压"},
        "paths": {"code": ["old-code"], "documents": ["old-docs"], "tests": [], "outputs": []},
        "analysis": {"include": ["documents"]},
    }
    bindings = {
        "version": 1,
        "projects": {
            "low-voltage": {
                "folders": [
                    {"path": "low-voltage/algorithm", "role": "code"},
                    {"path": "low-voltage/资料", "role": "documents"},
                ]
            }
        },
    }
    effective, meta = sentinel_runtime.apply_runtime_bindings(root, manifest, bindings)
    assert effective["paths"]["code"] == ["algorithm"]
    assert effective["paths"]["documents"] == ["资料"]
    assert "code" not in effective["analysis"]["include"]
    assert effective["repositories"][0]["local_path"] == "algorithm"
    assert meta["runtime_repositories"] == 1
    assert meta["selected"] == 2
    assert manifest["paths"]["code"] == ["old-code"]


def test_binding_file_roundtrip(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    path = state / "local-project-bindings.json"
    monkeypatch.setattr(local_control, "STATE_ROOT", state)
    monkeypatch.setattr(local_control, "BINDINGS_PATH", path)
    payload = {"version": 1, "projects": {"p1": {"folders": [{"path": "p1/docs", "role": "documents"}]}}}
    local_control._save_bindings(payload)
    assert local_control._load_bindings() == payload
    assert json.loads(path.read_text(encoding="utf-8"))["projects"]["p1"]["folders"][0]["role"] == "documents"
