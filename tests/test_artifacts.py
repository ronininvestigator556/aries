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
