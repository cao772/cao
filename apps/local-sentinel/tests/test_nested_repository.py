from pathlib import Path

from sentinel import resolve_git_root


def test_resolve_nested_repository_inside_project(tmp_path: Path):
    project = tmp_path / "algorithm版本管理"
    repo = project / "algorithm-ryj"
    repo.mkdir(parents=True)

    resolved, relative = resolve_git_root(
        project,
        {"repository": {"local_path": "algorithm-ryj"}},
    )

    assert resolved == repo.resolve()
    assert relative == "algorithm-ryj"


def test_reject_repository_path_outside_project(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()

    resolved, relative = resolve_git_root(
        project,
        {"repository": {"local_path": "../outside"}},
    )

    assert resolved is None
    assert relative == "../outside"
