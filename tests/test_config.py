from pathlib import Path

import pytest

from aries.cli import Aries
from aries.config import Config, get_default_config_yaml, load_config, migrate_config_data
from aries.exceptions import ConfigError


def test_default_config_contains_conversation_section(tmp_path: Path) -> None:
    yaml_text = get_default_config_yaml()
    assert "conversation" in yaml_text

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml_text, encoding="utf-8")

    config = load_config(config_path)
    assert config.conversation.max_context_tokens > 0


def test_legacy_prompts_default_migrates_to_profile() -> None:
    migrated, warnings = migrate_config_data({"prompts": {"default": "legacy"}})
    assert migrated["profiles"]["default"] == "legacy"
    assert any("prompts.default" in msg for msg in warnings)


def test_missing_profile_raises_clear_error(tmp_path: Path) -> None:
    config = Config()
    config.profiles.directory = tmp_path / "profiles"
    config.profiles.default = "absent"
    config.prompts.directory = tmp_path / "prompts"
    config.workspace.root = tmp_path / "workspaces"

    config.profiles.directory.mkdir(parents=True)
    (config.profiles.directory / "available.yaml").write_text(
        "name: available\nsystem_prompt: here", encoding="utf-8"
    )

    with pytest.raises(ConfigError) as excinfo:
        Aries(config)

    message = str(excinfo.value)
    assert "Available profiles: available" in message
    assert "Profile 'absent' not found" in message


def test_default_profile_uses_yaml_without_warnings(tmp_path: Path) -> None:
    config = Config()
    config.profiles.directory = tmp_path / "profiles"
    config.prompts.directory = tmp_path / "prompts"
    config.workspace.root = tmp_path / "workspaces"
    config.tools.allow_network = True
    config.tools.allow_shell = True

    config.profiles.directory.mkdir(parents=True)
    (config.profiles.directory / "default.yaml").write_text(
        "name: default\nsystem_prompt: profile prompt", encoding="utf-8"
    )

    app = Aries(config)

    assert app.conversation.system_prompt == "profile prompt"
    assert app.current_prompt == "default"
    assert not app._warnings_shown


def test_default_profile_falls_back_to_legacy_prompt(tmp_path: Path) -> None:
    config = Config()
    config.profiles.directory = tmp_path / "profiles"
    config.prompts.directory = tmp_path / "prompts"
    config.workspace.root = tmp_path / "workspaces"

    config.prompts.directory.mkdir(parents=True, exist_ok=True)
    (config.prompts.directory / "default.md").write_text("legacy prompt", encoding="utf-8")
    config.profiles.directory.mkdir(parents=True, exist_ok=True)

    app = Aries(config)

    assert app.conversation.system_prompt == "legacy prompt"
    assert "legacy_prompt:default" in app._warnings_shown


def test_profiles_require_blocks_legacy_fallback(tmp_path: Path) -> None:
    config = Config()
    config.profiles.directory = tmp_path / "profiles"
    config.profiles.require = True
    config.prompts.directory = tmp_path / "prompts"
    config.workspace.root = tmp_path / "workspaces"

    config.prompts.directory.mkdir(parents=True, exist_ok=True)
    (config.prompts.directory / "default.md").write_text("legacy prompt", encoding="utf-8")
    config.profiles.directory.mkdir(parents=True, exist_ok=True)

    with pytest.raises(ConfigError):
        Aries(config)
