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

from aries.config import ToolsConfig, WorkspaceConfig
from aries.exceptions import FileToolError


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


logger = logging.getLogger(__name__)


def resolve_and_validate_path(
    path: str | Path,
    *,
    workspace: "Workspace | Path | None" = None,
    allowed_paths: Iterable[Path] | None = None,
    denied_paths: Iterable[Path] | None = None,
) -> Path:
    """Resolve a path against workspace and policy constraints.

    The returned path is absolute, symlinks are resolved, and the location is
    checked against both allowed and denied path lists. Relative paths are
    interpreted relative to the current workspace root when provided for
    ergonomics.

    Raises:
        FileToolError: If the path is outside allowed roots or inside denied roots.
    """

    try:
        raw_path = Path(path).expanduser()
    except Exception as exc:  # pragma: no cover - Path construction rarely fails
        raise FileToolError(f"Invalid path: {path}") from exc

    is_relative = not raw_path.is_absolute()
    # Prefer resolving relative paths against the workspace root for consistency
    # across tools, artifact registration, and workspace management commands.
    if is_relative:
        base: Path
        if isinstance(workspace, Workspace):
            base = workspace.root
        elif workspace:
            base = Path(workspace)
        else:
            base = Path.cwd()
        raw_path = base / raw_path

    try:
        resolved = raw_path.resolve(strict=False)
    except Exception as exc:  # pragma: no cover - resolution errors are rare
        raise FileToolError(f"Failed to resolve path: {path}") from exc

    allowed_roots: list[Path] = []
    if workspace:
        if isinstance(workspace, Workspace):
            base_root = workspace.root
        else:
            base_root = Path(workspace)
        allowed_roots.append(base_root.expanduser().resolve())
    if allowed_paths:
        allowed_roots.extend(Path(p).expanduser().resolve() for p in allowed_paths)

    denied_roots = [Path(p).expanduser().resolve() for p in denied_paths or []]

    def _under_root(target: Path) -> bool:
        try:
            return resolved.is_relative_to(target)
        except AttributeError:  # pragma: no cover - for Python <3.9 compatibility
            return str(resolved).startswith(str(target))
        except ValueError:
            return False

    for denied in denied_roots:
        if _under_root(denied):
            raise FileToolError(f"Path denied by policy: {resolved}")

    if is_relative and workspace:
        workspace_root = workspace.root if isinstance(workspace, Workspace) else Path(workspace)
        workspace_root = workspace_root.expanduser().resolve()
        if not _under_root(workspace_root):
            raise FileToolError(f"Relative path escapes workspace: {resolved}")

    if allowed_roots and not any(_under_root(root) for root in allowed_roots):
        raise FileToolError(f"Path outside allowed locations: {resolved}")

    return resolved


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


@dataclass
class ArtifactRef:
    """Structured artifact reference."""

    path: Path
    description: str | None = None
    source: str | None = None
    name: str | None = None
    mime: str | None = None
    type: str | None = None
    size_bytes: int | None = None
    hash: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_hint(cls, hint: Any) -> "ArtifactRef | None":
        """Create an ArtifactRef from a hint object."""

        if isinstance(hint, cls):
            return hint

        if isinstance(hint, (str, Path)):
            return cls(path=Path(hint))

        if not isinstance(hint, dict):
            return None

        path_value = hint.get("path")
        if not path_value:
            return None

        known_keys = {
            "path",
            "description",
            "source",
            "name",
            "mime",
            "mime_type",
            "type",
            "size_bytes",
            "hash",
        }

        extra = {k: v for k, v in hint.items() if k not in known_keys and v is not None}

        return cls(
            path=Path(path_value),
            description=hint.get("description"),
            source=hint.get("source"),
            name=hint.get("name"),
            mime=hint.get("mime") or hint.get("mime_type"),
            type=hint.get("type"),
            size_bytes=hint.get("size_bytes"),
            hash=hint.get("hash"),
            extra=extra,
        )


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

    def _dedupe_key(self, record: dict[str, Any]) -> tuple[str, str, int | None]:
        """Compute deduplication key for a manifest record."""
        hash_value = record.get("hash")
        if hash_value:
            return ("hash", hash_value, record.get("path", ""))
        return ("size", record.get("path", ""), record.get("size_bytes"))

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
        new_key = self._dedupe_key(record)
        for existing in manifest:
            if self._dedupe_key(existing) == new_key:
                return existing

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

    def __init__(self, config: WorkspaceConfig, tools_config: ToolsConfig | None = None) -> None:
        self.config = config
        self.tools_config = tools_config
        self.root = Path(config.root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self.current: Workspace | None = None
        self.logger: TranscriptLogger | None = None
        self.artifacts: ArtifactRegistry | None = None

    def resolve_path(self, path: str | Path) -> Path:
        """Resolve a path using workspace and tool policy settings."""

        allowed_paths = None
        denied_paths = None
        if self.tools_config:
            allowed_paths = self.tools_config.allowed_paths
            denied_paths = self.tools_config.denied_paths

        return resolve_and_validate_path(
            path,
            workspace=self.current,
            allowed_paths=allowed_paths,
            denied_paths=denied_paths,
        )

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
        target = self.resolve_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(target, "w:gz") as tar:
            tar.add(self.current.root, arcname=self.current.root.name)
        return target

    def import_bundle(self, bundle: Path) -> Workspace:
        bundle = self.resolve_path(bundle)
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

        ref = ArtifactRef.from_hint(artifact)
        if not ref:
            logger.warning("Artifact hint missing path; skipping registration: %s", artifact)
            return None

        try:
            path = self.resolve_path(ref.path)
        except FileToolError as exc:
            logger.warning("Artifact outside allowed paths ignored: %s", exc)
            return None

        if not path.exists():
            logger.warning("Artifact path not found for registration: %s", path)
            return None

        extra = {
            "description": ref.description,
            "source": ref.source,
            "name": ref.name or path.name,
            "mime": ref.mime,
            "type": ref.type,
            "size_bytes": ref.size_bytes,
            "hash": ref.hash,
        }
        extra.update(ref.extra)
        return self.artifacts.register_file(
            path,
            description=extra.pop("description"),
            source=source or extra.pop("source"),
            extra=extra,
        )
