from __future__ import annotations

from pathlib import Path

from aries.core.file_edit import FileEditPipeline


def test_patch_apply_success(tmp_path: Path) -> None:
    file_path = tmp_path / "demo.txt"
    file_path.write_text("hello\n", encoding="utf-8")
    artifact_dir = tmp_path / "artifacts"

    pipeline = FileEditPipeline(
        workspace=tmp_path,
        allowed_paths=[tmp_path],
        artifact_dir=artifact_dir,
    )
    diff = pipeline.propose_patch(str(file_path), "hello\nworld\n", "add a line")
    result = pipeline.apply_patch(str(file_path), diff)

    assert result.success is True
    assert "Patch applied" in result.message
    assert file_path.read_text(encoding="utf-8") == "hello\nworld\n"
    assert result.artifact is not None


def test_patch_apply_rejects_path_escape(tmp_path: Path) -> None:
    pipeline = FileEditPipeline(workspace=tmp_path, allowed_paths=[tmp_path])
    diff = """--- a/escape.txt\n+++ b/escape.txt\n@@ -1 +1 @@\n-hello\n+goodbye\n"""

    result = pipeline.apply_patch("../escape.txt", diff)

    assert result.success is False
    assert "workspace" in result.message.lower()
