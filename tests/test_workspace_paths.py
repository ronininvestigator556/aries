from pathlib import Path

import pytest

from aries.config import Config
from aries.core.workspace import WorkspaceManager
from aries.exceptions import FileToolError


def _make_workspace(tmp_path: Path) -> WorkspaceManager:
    config = Config()
    config.workspace.root = tmp_path / "workspaces"
    config.workspace.persist_by_default = True
    config.workspace.default = "demo"
    config.tools.allowed_paths = [config.workspace.root]
    manager = WorkspaceManager(config.workspace, config.tools)
    manager.new("demo")
    return manager


def test_resolve_relative_path_within_workspace(tmp_path: Path) -> None:
    manager = _make_workspace(tmp_path)
    resolved = manager.resolve_path("notes/info.txt")

    assert resolved == (manager.current.root / "notes" / "info.txt").resolve()


def test_resolve_rejects_parent_traversal(tmp_path: Path) -> None:
    manager = _make_workspace(tmp_path)

    with pytest.raises(FileToolError):
        manager.resolve_path("../escape.txt")


def test_resolve_rejects_symlink_escape(tmp_path: Path) -> None:
    manager = _make_workspace(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    target_dir = manager.current.root / "artifacts"
    target_dir.mkdir(parents=True, exist_ok=True)
    symlink_path = target_dir / "link.txt"
    symlink_path.symlink_to(outside)

    with pytest.raises(FileToolError):
        manager.resolve_path(symlink_path)
