from __future__ import annotations

from pathlib import Path

from aries.config import Config
from aries.core.desktop_ops import DesktopOpsMode, RunContext
from aries.core.desktop_recipes import DesktopRecipeRegistry


def _context(tmp_path: Path) -> RunContext:
    return RunContext(
        goal="",
        cwd=tmp_path,
        repo_root=None,
        virtualenv=None,
        mode=DesktopOpsMode.COMMANDER,
        allowed_roots=[tmp_path],
    )


def test_repo_clone_open_plan_prefers_fetch_when_present(tmp_path: Path) -> None:
    config = Config().desktop_ops
    registry = DesktopRecipeRegistry(config)
    dest = tmp_path / "demo-repo"
    (dest / ".git").mkdir(parents=True)

    context = _context(tmp_path)
    plan = registry.plan(
        "repo_clone_open",
        {"repo_url": "https://example.com/repo.git", "dest_dir": str(dest)},
        context,
    )

    assert plan.steps[0].name == "fetch_updates"
    assert plan.steps[1].name == "status"
    assert plan.done_criteria(context, []) is True
    assert context.repo_root == dest.resolve()


def test_python_bootstrap_includes_requested_extras(tmp_path: Path) -> None:
    config = Config().desktop_ops
    config.python_bootstrap_extras = ["dev", "rag"]
    registry = DesktopRecipeRegistry(config)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    plan = registry.plan(
        "python_bootstrap",
        {"repo_root": str(repo_root), "venv_dir": ".venv"},
        _context(tmp_path),
    )

    install_step = plan.steps[2]
    assert "-e '.[dev,rag]'" in install_step.arguments["command"]
