from pathlib import Path

import pytest

from aries.cli import Aries
from aries.commands.profile import ProfileCommand
from aries.config import Config


@pytest.mark.anyio
async def test_profile_use_preserves_tool_policy_defaults(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir(parents=True)
    (profile_dir / "default.yaml").write_text("name: default\nsystem_prompt: base", encoding="utf-8")
    (profile_dir / "alt.yaml").write_text("name: alt\nsystem_prompt: alt prompt", encoding="utf-8")

    config = Config()
    config.profiles.directory = profile_dir
    config.prompts.directory = tmp_path / "prompts"
    config.workspace.root = tmp_path / "workspaces"
    config.tools.allow_shell = True
    config.tools.allow_network = True

    app = Aries(config)
    command = ProfileCommand()

    await command.execute(app, "use alt")

    assert app.current_prompt == "alt"
    assert app.conversation.system_prompt == "alt prompt"
    assert app.tool_policy.config.allow_shell is True
    assert app.tool_policy.config.allow_network is True
