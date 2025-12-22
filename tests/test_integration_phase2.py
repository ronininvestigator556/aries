import json
import textwrap
from pathlib import Path

import pytest

from aries.cli import Aries
from aries.commands.profile import ProfileCommand
from aries.config import Config, load_config
from aries.core.message import ToolCall


@pytest.mark.anyio
async def test_workspace_flow_and_profile_switch(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir(parents=True)
    (profile_dir / "default.yaml").write_text("name: default\nsystem_prompt: default prompt", encoding="utf-8")
    (profile_dir / "alt.yaml").write_text("name: alt\nsystem_prompt: alt prompt", encoding="utf-8")

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
        id="wf-1",
        name="write_file",
        arguments={"path": str(config.workspace.root / "demo" / "notes.txt"), "content": "hello world"},
    )
    await app._execute_tool_calls([call])

    transcript_path = config.workspace.root / "demo" / "transcripts" / "transcript.ndjson"
    logs = [json.loads(line) for line in transcript_path.read_text(encoding="utf-8").splitlines()]
    assert any(entry.get("role") == "tool" for entry in logs)

    manifest_path = config.workspace.root / "demo" / "artifacts" / "manifest.json"
    artifacts = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert any("notes.txt" in entry.get("path", "") for entry in artifacts)

    profile_cmd = ProfileCommand()
    await profile_cmd.execute(app, "use alt")

    assert app.current_prompt == "alt"
    assert app.conversation.system_prompt == "alt prompt"


@pytest.mark.anyio
async def test_legacy_prompts_default_warns_once_and_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "legacy.md").write_text("legacy prompt", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            workspace:
              root: "./work"
              default: "demo"
              persist_by_default: true
            tools:
              confirmation_required: false
              allowed_paths:
                - "."
            prompts:
              directory: "./prompts"
              default: "legacy"
            """
        ).strip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    config = load_config(config_path)
    app = Aries(config)

    captured = capsys.readouterr()
    assert "legacy prompt file" in captured.out
    assert captured.out.count("legacy prompt file") == 1

    call = ToolCall(
        id="legacy-1",
        name="write_file",
        arguments={"path": str(tmp_path / "work" / "demo" / "note.txt"), "content": "persist me"},
    )
    await app._execute_tool_calls([call])

    transcript_path = tmp_path / "work" / "demo" / "transcripts" / "transcript.ndjson"
    manifest_path = tmp_path / "work" / "demo" / "artifacts" / "manifest.json"
    assert transcript_path.exists()
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert any(entry.get("path", "").endswith("note.txt") for entry in manifest)
