from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class TranscriptEpisode:
    name: str
    command: str
    outputs: list[str]


def load_episodes(path: Path) -> list[TranscriptEpisode]:
    text = path.read_text(encoding="utf-8")
    episodes: list[TranscriptEpisode] = []
    current_name = None
    current_command = None
    outputs: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("=== EPISODE:"):
            if current_name and current_command:
                episodes.append(TranscriptEpisode(current_name, current_command, outputs))
            current_name = line.replace("=== EPISODE:", "").strip().rstrip("=").strip()
            current_command = None
            outputs = []
            continue
        if line.startswith("start_process:"):
            current_command = line.replace("start_process:", "").strip()
            continue
        if line.startswith("read_process_output:"):
            outputs.append(line.replace("read_process_output:", "").strip())
            continue
    if current_name and current_command:
        episodes.append(TranscriptEpisode(current_name, current_command, outputs))
    return episodes
