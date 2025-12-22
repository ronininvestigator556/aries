import json
import logging
from pathlib import Path

import pytest

from aries.cli import Aries
from aries.config import Config
from aries.core.message import ToolCall
from aries.tools.base import ToolResult


@pytest.mark.anyio
async def test_artifact_hint_registration(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir(parents=True)
    (profile_dir / "default.yaml").write_text("name: default\nsystem_prompt: default", encoding="utf-8")

    config = Config()
    config.profiles.directory = profile_dir
    config.prompts.directory = tmp_path / "prompts"
    config.workspace.root = tmp_path / "workspaces"
    config.workspace.persist_by_default = True
    config.workspace.default = "demo"
    config.tools.allowed_paths = [tmp_path]
    config.tools.confirmation_required = False

    app = Aries(config)
    call = ToolCall(
        id="call-1",
        name="write_file",
        arguments={
            "path": str(config.workspace.root / "demo" / "output.txt"),
            "content": "artifact data",
        },
    )

    await app._execute_tool_calls([call])

    manifest_path = config.workspace.root / "demo" / "artifacts" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert any(entry.get("name") == "output.txt" for entry in manifest)


@pytest.mark.anyio
async def test_legacy_metadata_path_registers_artifact(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir(parents=True)
    (profile_dir / "default.yaml").write_text("name: default\nsystem_prompt: default", encoding="utf-8")

    config = Config()
    config.profiles.directory = profile_dir
    config.prompts.directory = tmp_path / "prompts"
    config.workspace.root = tmp_path / "workspaces"
    config.workspace.persist_by_default = True
    config.workspace.default = "demo"
    config.tools.allowed_paths = [tmp_path]
    config.tools.confirmation_required = False

    app = Aries(config)
    legacy_path = config.workspace.root / "demo" / "legacy.txt"
    legacy_path.write_text("legacy artifact", encoding="utf-8")

    result = ToolResult(success=True, content="ok", metadata={"path": str(legacy_path)})
    app._maybe_register_artifact(result, "custom_tool")

    manifest_path = config.workspace.root / "demo" / "artifacts" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert any(entry.get("path") == str(legacy_path) for entry in manifest)


@pytest.mark.anyio
async def test_missing_artifact_path_logs_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir(parents=True)
    (profile_dir / "default.yaml").write_text("name: default\nsystem_prompt: default", encoding="utf-8")

    config = Config()
    config.profiles.directory = profile_dir
    config.prompts.directory = tmp_path / "prompts"
    config.workspace.root = tmp_path / "workspaces"
    config.workspace.persist_by_default = True
    config.workspace.default = "demo"
    config.tools.allowed_paths = [tmp_path]
    config.tools.confirmation_required = False

    app = Aries(config)

    caplog.set_level(logging.WARNING, logger="aries.core.workspace")
    missing = config.workspace.root / "demo" / "nope.txt"
    result = ToolResult(success=True, content="", metadata={"path": str(missing)})
    app._maybe_register_artifact(result, "custom_tool")

    warnings = [rec.message for rec in caplog.records]
    assert any("Artifact path not found" in msg for msg in warnings)


@pytest.mark.anyio
async def test_artifact_registered_only_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir(parents=True)
    (profile_dir / "default.yaml").write_text("name: default\nsystem_prompt: default", encoding="utf-8")

    config = Config()
    config.profiles.directory = profile_dir
    config.prompts.directory = tmp_path / "prompts"
    config.workspace.root = tmp_path / "workspaces"
    config.workspace.persist_by_default = True
    config.workspace.default = "demo"
    config.tools.allowed_paths = [tmp_path]
    config.tools.confirmation_required = False

    artifact_path = config.workspace.root / "demo" / "output.txt"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text("data", encoding="utf-8")

    app = Aries(config)
    call_counts = {"register_file": 0, "register_hint": 0}

    original_register_file = app.workspace.artifacts.register_file
    original_register_hint = app.workspace.register_artifact_hint

    def _record_register_file(*args: object, **kwargs: object):
        call_counts["register_file"] += 1
        return original_register_file(*args, **kwargs)

    def _record_register_hint(*args: object, **kwargs: object):
        call_counts["register_hint"] += 1
        return original_register_hint(*args, **kwargs)

    monkeypatch.setattr(app.workspace.artifacts, "register_file", _record_register_file)
    monkeypatch.setattr(app.workspace, "register_artifact_hint", _record_register_hint)

    result = ToolResult(
        success=True,
        content="ok",
        metadata={"artifact": {"path": str(artifact_path), "description": "desc"}, "path": str(artifact_path)},
    )
    app._maybe_register_artifact(result, "write_file")

    manifest_path = config.workspace.root / "demo" / "artifacts" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert len(manifest) == 1
    assert manifest[0]["description"] == "desc"
    assert call_counts["register_file"] == 1
    assert call_counts["register_hint"] == 0
