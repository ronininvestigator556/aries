"""
Workspace, transcript, and artifact management.
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import tarfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from aries.config import WorkspaceConfig


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


logger = logging.getLogger(__name__)


@dataclass
class TranscriptEntry:
    """Structured log entry for transcripts."""

    timestamp: str
    role: str
    content: str
    conversation_id: str
    message_id: str
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        payload = {
            "timestamp": self.timestamp,
            "role": self.role,
            "content": self.content,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
        }
        if self.extra:
            payload.update(self.extra)
        return json.dumps(payload, ensure_ascii=False)


class TranscriptLogger:
    """Append-only NDJSON transcript writer."""

    def __init__(self, transcript_path: Path) -> None:
        self.transcript_path = transcript_path
        self.transcript_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, entry: TranscriptEntry) -> None:
        line = entry.to_json()
        with self.transcript_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


class ArtifactRegistry:
    """Manage artifacts and their provenance."""

    def __init__(self, artifact_root: Path) -> None:
        self.artifact_root = artifact_root
        self.manifest_path = artifact_root / "manifest.json"
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        if not self.manifest_path.exists():
            self._write_manifest([])

    def _read_manifest(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _write_manifest(self, records: Iterable[dict[str, Any]]) -> None:
        temp_path = self.manifest_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(list(records), indent=2), encoding="utf-8")
        temp_path.replace(self.manifest_path)

    def register_file(
        self,
        path: Path,
        description: str | None = None,
        source: str | None = None,
        *,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register an artifact and return its record."""
        path = path.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(path)

        extra_data = extra or {}

        hash_value = extra_data.get("hash")
        if not hash_value:
            sha256 = hashlib.sha256()
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha256.update(chunk)
            hash_value = sha256.hexdigest()

        size_bytes = extra_data.get("size_bytes") or path.stat().st_size
        mime_guess = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        mime_type = extra_data.get("mime") or extra_data.get("mime_type") or mime_guess

        record = {
            "path": str(path),
            "created_at": _now_iso(),
            "mime_type": mime_type,
            "size_bytes": size_bytes,
            "hash": hash_value,
            "description": description or extra_data.get("description"),
            "source": source or extra_data.get("source"),
            "type": extra_data.get("type"),
            "name": extra_data.get("name") or path.name,
        }

        manifest = self._read_manifest()
        if any(r.get("hash") == record["hash"] for r in manifest):
            return record

        manifest.append(record)
        self._write_manifest(manifest)
        return record

    def all(self) -> list[dict[str, Any]]:
        return self._read_manifest()


@dataclass
class Workspace:
    """A persisted workspace context."""

    name: str
    root: Path
    created_at: str
    manifest: Path
    transcript_dir: Path
    artifact_dir: Path
    index_dir: Path


class WorkspaceManager:
    """Create, open, close, and export workspaces."""

    def __init__(self, config: WorkspaceConfig) -> None:
        self.config = config
        self.root = Path(config.root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self.current: Workspace | None = None
        self.logger: TranscriptLogger | None = None
        self.artifacts: ArtifactRegistry | None = None

    def _workspace_paths(self, name: str) -> Workspace:
        root = self.root / name
        return Workspace(
            name=name,
            root=root,
            created_at=_now_iso(),
            manifest=root / self.config.manifest_name,
            transcript_dir=root / self.config.transcript_dirname,
            artifact_dir=root / self.config.artifact_dirname,
            index_dir=root / self.config.indexes_dirname,
        )

    def list(self) -> list[str]:
        return sorted([p.name for p in self.root.iterdir() if p.is_dir()])

    def new(self, name: str) -> Workspace:
        workspace = self._workspace_paths(name)
        workspace.root.mkdir(parents=True, exist_ok=True)
        workspace.transcript_dir.mkdir(parents=True, exist_ok=True)
        workspace.artifact_dir.mkdir(parents=True, exist_ok=True)
        workspace.index_dir.mkdir(parents=True, exist_ok=True)

        manifest_data = {
            "name": name,
            "created_at": workspace.created_at,
            "transcripts": str(workspace.transcript_dir),
            "artifacts": str(workspace.artifact_dir),
            "indexes": str(workspace.index_dir),
        }
        workspace.manifest.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
        return self.open(name)

    def open(self, name: str) -> Workspace:
        workspace = self._workspace_paths(name)
        if not workspace.root.exists():
            raise FileNotFoundError(f"Workspace '{name}' not found")
        workspace.transcript_dir.mkdir(parents=True, exist_ok=True)
        workspace.artifact_dir.mkdir(parents=True, exist_ok=True)
        workspace.index_dir.mkdir(parents=True, exist_ok=True)
        self.current = workspace
        transcript_file = workspace.transcript_dir / "transcript.ndjson"
        self.logger = TranscriptLogger(transcript_file)
        self.artifacts = ArtifactRegistry(workspace.artifact_dir)
        return workspace

    def close(self) -> None:
        self.current = None
        self.logger = None
        self.artifacts = None

    def export(self, target: Path) -> Path:
        if not self.current:
            raise RuntimeError("No active workspace to export")
        target = Path(target).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(target, "w:gz") as tar:
            tar.add(self.current.root, arcname=self.current.root.name)
        return target

    def import_bundle(self, bundle: Path) -> Workspace:
        bundle = Path(bundle).expanduser()
        if not bundle.exists():
            raise FileNotFoundError(bundle)
        with tarfile.open(bundle, "r:gz") as tar:
            top = tar.getmembers()[0].name.split("/")[0]
            target_dir = self.root / top
            if target_dir.exists():
                raise FileExistsError(f"Workspace '{top}' already exists")
            tar.extractall(self.root)
        return self.open(top)

    def register_artifact_hint(
        self,
        artifact: dict[str, Any] | Path,
        source: str | None = None,
    ) -> dict[str, Any] | None:
        """Register an artifact from a tool or workflow hint.

        Args:
            artifact: Artifact path or metadata hint containing at least a path.
            source: Optional source label for provenance.

        Returns:
            Manifest record or None if registration was skipped.
        """
        if not self.artifacts:
            return None

        hint = {"path": str(artifact)} if isinstance(artifact, Path) else dict(artifact)
        path_value = hint.get("path")
        if not path_value:
            return None

        path = Path(path_value).expanduser()
        if not path.exists():
            logger.warning("Artifact path not found for registration: %s", path)
            return None

        extra = {
            "description": hint.get("description"),
            "source": hint.get("source"),
            "name": hint.get("name") or path.name,
            "mime": hint.get("mime"),
            "type": hint.get("type"),
            "size_bytes": hint.get("size_bytes"),
            "hash": hint.get("hash"),
        }
        return self.artifacts.register_file(
            path,
            description=extra.pop("description"),
            source=source or extra.pop("source"),
            extra=extra,
        )
