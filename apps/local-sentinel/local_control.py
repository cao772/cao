from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

PROJECTS_ROOT = Path(os.getenv("PROJECTS_ROOT", "/projects"))
STATE_ROOT = Path(os.getenv("SENTINEL_STATE_ROOT", "/state"))
BINDINGS_PATH = STATE_ROOT / "local-project-bindings.json"
USER_ID = os.getenv("USER_ID", "developer")
DEVICE_ID = os.getenv("DEVICE_ID", "local-device")
HIDDEN_NAMES = {".git", "node_modules", ".venv", "__pycache__", ".DS_Store"}
VALID_ROLES = {"code", "documents", "tests", "outputs"}

app = FastAPI(title="Project Sentinel Local Control", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8088", "http://localhost:8088"],
    allow_credentials=False,
    allow_methods=["GET", "PUT", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class FolderBinding(BaseModel):
    path: str = Field(min_length=1, max_length=2000)
    role: str = Field(pattern="^(code|documents|tests|outputs)$")


class FolderBindingSet(BaseModel):
    folders: list[FolderBinding] = Field(default_factory=list, max_length=200)


def _load_bindings() -> dict[str, Any]:
    if not BINDINGS_PATH.exists():
        return {"version": 1, "projects": {}}
    try:
        data = json.loads(BINDINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "projects": {}}
    if not isinstance(data, dict):
        return {"version": 1, "projects": {}}
    data.setdefault("version", 1)
    data.setdefault("projects", {})
    return data


def _save_bindings(data: dict[str, Any]) -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = BINDINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(BINDINGS_PATH)


def _discover_local_projects() -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    if not PROJECTS_ROOT.exists():
        return result
    root = PROJECTS_ROOT.resolve()
    for child in sorted(PROJECTS_ROOT.iterdir(), key=lambda item: item.name.lower()):
        manifest_path = child / "project.yaml"
        if not child.is_dir() or not manifest_path.is_file():
            continue
        try:
            resolved = child.resolve()
            resolved.relative_to(root)
            data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            project = data.get("project") or {}
            project_id = str(project.get("id") or "").strip()
            if project_id:
                result.append(
                    {
                        "project_id": project_id,
                        "project_name": str(project.get("name") or project_id),
                        "root": resolved.relative_to(root).as_posix(),
                    }
                )
        except (OSError, ValueError, yaml.YAMLError):
            continue
    return result


def _project_root(project_id: str) -> Path:
    root = PROJECTS_ROOT.resolve()
    for item in _discover_local_projects():
        if item["project_id"] == project_id:
            return (PROJECTS_ROOT / item["root"]).resolve()
    raise HTTPException(status_code=404, detail="本机未发现该 project_id 的 project.yaml")


def resolve_authorized_folder(raw: str) -> Path:
    text = raw.strip().replace("\\", "/").strip("/")
    if not text or text == "." or "\x00" in text:
        raise HTTPException(status_code=422, detail="请选择 /projects 下的具体目录")
    if raw.startswith("/") or any(part == ".." for part in Path(text).parts):
        raise HTTPException(status_code=422, detail="目录必须位于已授权的 /projects 范围内")
    root = PROJECTS_ROOT.resolve()
    candidate = (PROJECTS_ROOT / text).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="目录超出已授权的 /projects 范围") from exc
    if not candidate.exists() or not candidate.is_dir():
        raise HTTPException(status_code=404, detail=f"目录不存在：{text}")
    return candidate


def _folder_node(path: Path, depth: int, max_children: int) -> dict[str, Any]:
    root = PROJECTS_ROOT.resolve()
    relative = path.resolve().relative_to(root).as_posix()
    node: dict[str, Any] = {"name": path.name, "path": relative, "children": []}
    if depth <= 0:
        return node
    children: list[Path] = []
    try:
        for child in path.iterdir():
            if child.name in HIDDEN_NAMES or child.name.startswith(".~") or child.name.startswith("~$"):
                continue
            try:
                resolved = child.resolve()
                resolved.relative_to(root)
            except (OSError, ValueError):
                continue
            if child.is_dir():
                children.append(child)
    except OSError:
        return node
    children.sort(key=lambda item: item.name.lower())
    node["children"] = [_folder_node(child, depth - 1, max_children) for child in children[:max_children]]
    node["truncated"] = len(children) > max_children
    return node


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "local-control", "projects_root": "/projects"}


@app.get("/api/v1/local/info")
def local_info() -> dict[str, Any]:
    return {
        "user_id": USER_ID,
        "device_id": DEVICE_ID,
        "projects_root": "/projects",
        "bindings_file": str(BINDINGS_PATH),
        "sentinel_available": True,
        "projects": _discover_local_projects(),
    }


@app.get("/api/v1/local/folders")
def local_folders(
    depth: int = Query(default=3, ge=1, le=6),
    max_children: int = Query(default=100, ge=10, le=500),
    project_id: str | None = Query(default=None, max_length=200),
) -> dict[str, Any]:
    if not PROJECTS_ROOT.exists():
        return {"root": "/projects", "folders": [], "available": False}
    folders: list[dict[str, Any]] = []
    if project_id:
        project_root = _project_root(project_id)
        folders = [_folder_node(project_root, depth, max_children)]
    else:
        for child in sorted(PROJECTS_ROOT.iterdir(), key=lambda item: item.name.lower()):
            if not child.is_dir() or child.name in HIDDEN_NAMES or child.name.startswith("."):
                continue
            try:
                child.resolve().relative_to(PROJECTS_ROOT.resolve())
            except (OSError, ValueError):
                continue
            folders.append(_folder_node(child, depth - 1, max_children))
    return {"root": "/projects", "folders": folders, "available": True}


@app.get("/api/v1/local/bindings")
def get_bindings() -> dict[str, Any]:
    return _load_bindings()


@app.put("/api/v1/local/projects/{project_id}/bindings")
def put_bindings(project_id: str, payload: FolderBindingSet) -> dict[str, Any]:
    project_root = _project_root(project_id)
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in payload.folders:
        if item.role not in VALID_ROLES:
            raise HTTPException(status_code=422, detail=f"不支持的目录用途：{item.role}")
        resolved = resolve_authorized_folder(item.path)
        try:
            resolved.relative_to(project_root)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="所选目录不属于当前业务项目的本机项目根目录") from exc
        relative = resolved.relative_to(PROJECTS_ROOT.resolve()).as_posix()
        identity = (relative, item.role)
        if identity in seen:
            continue
        seen.add(identity)
        normalized.append({"path": relative, "role": item.role})

    data = _load_bindings()
    projects = data.setdefault("projects", {})
    projects[project_id] = {"folders": normalized}
    _save_bindings(data)
    return {"project_id": project_id, "folders": normalized, "saved": True}


@app.post("/api/v1/local/projects/{project_id}/scan")
def scan_project(project_id: str) -> dict[str, Any]:
    from sentinel_runtime import scan_once

    result = scan_once(only_project_id=project_id)
    if result.get("matched", 0) == 0:
        raise HTTPException(status_code=404, detail="本机未发现该 project_id 的 project.yaml")
    return result
