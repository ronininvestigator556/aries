import json
from pathlib import Path

import pytest

from aries.cli import Aries
from aries.config import Config
from aries.core.message import ToolCall


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
