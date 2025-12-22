"""
Prompt profiles management.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Profile:
    name: str
    description: str | None
    system_prompt: str | None
    tool_policy: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None


class ProfileManager:
    """Load and manage profiles from YAML files."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory).expanduser()
        self.directory.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[str]:
        return sorted([p.stem for p in self.directory.glob("*.yaml")])

    def load(self, name: str) -> Profile:
        path = self.directory / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Profile '{name}' not found")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return Profile(
            name=data.get("name", name),
            description=data.get("description"),
            system_prompt=data.get("system_prompt"),
            tool_policy=data.get("tool_policy"),
            output_schema=data.get("output_schema"),
        )

    def describe(self, name: str) -> str:
        profile = self.load(name)
        summary = [f"Name: {profile.name}"]
        if profile.description:
            summary.append(f"Description: {profile.description}")
        if profile.system_prompt:
            summary.append("System prompt: present")
        if profile.tool_policy:
            summary.append(f"Tool policy: {json.dumps(profile.tool_policy)}")
        if profile.output_schema:
            summary.append("Output schema defined")
        return "\n".join(summary)
