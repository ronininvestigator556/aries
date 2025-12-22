from pathlib import Path

from aries.config import Config, get_default_config_yaml, load_config


def test_default_config_contains_conversation_section(tmp_path: Path) -> None:
    yaml_text = get_default_config_yaml()
    assert "conversation" in yaml_text

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml_text, encoding="utf-8")

    config = load_config(config_path)
    assert config.conversation.max_context_tokens > 0
