from __future__ import annotations

import subprocess
from pathlib import Path

from multi_repository import configured_repositories, inspect_repositories


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _init_repo(path: Path, filename: str) -> None:
    path.mkdir(parents=True)
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    (path / filename).write_text("initial\n", encoding="utf-8")
    _git(path, "add", filename)
    _git(path, "commit", "-m", "initial")


def test_legacy_repository_is_wrapped_as_single_primary():
    repositories = configured_repositories(
        {"repository": {"provider": "gitlab", "url": "http://git/algorithm.git", "local_path": "algorithm"}}
    )
    assert len(repositories) == 1
    assert repositories[0]["id"] == "primary"
    assert repositories[0]["primary"] is True


def test_two_repositories_are_aggregated_into_one_project_git_state(tmp_path: Path):
    project = tmp_path / "low-voltage"
    frontend = project / "voltage-management"
    algorithm = project / "algorithm"
    _init_repo(frontend, "page.ts")
    _init_repo(algorithm, "service.py")

    # Only frontend has an uncommitted change. The project-level state must still
    # be dirty even when algorithm is the primary repository.
    (frontend / "page.ts").write_text("initial\nchanged\n", encoding="utf-8")

    manifest = {
        "repositories": [
            {
                "id": "frontend",
                "role": "frontend",
                "provider": "gitlab",
                "url": "http://git/frontend.git",
                "local_path": "voltage-management",
                "primary": False,
            },
            {
                "id": "algorithm",
                "role": "algorithm",
                "provider": "gitlab",
                "url": "http://git/algorithm.git",
                "local_path": "algorithm",
                "primary": True,
            },
        ]
    }

    aggregate, runtime = inspect_repositories(project, manifest)
    assert len(runtime) == 2
    assert aggregate["multi_repository"] is True
    assert aggregate["repository_count"] == 2
    assert aggregate["available_repository_count"] == 2
    assert aggregate["dirty"] is True
    assert aggregate["repository_id"] == "algorithm"
    changed = aggregate["changed_files"]
    assert len(changed) == 1
    assert changed[0]["repository_id"] == "frontend"
    assert changed[0]["repository_role"] == "frontend"
