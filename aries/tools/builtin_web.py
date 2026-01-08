"""
Builtin web tools for Aries.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from aries.config import get_config
from aries.core.workspace import ArtifactRegistry, resolve_and_validate_path
from aries.tools.base import BaseTool, ToolResult


_WHITESPACE_RE = re.compile(r"\s+")


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _error_result(
    *,
    error_type: str,
    message: str,
    retryable: bool,
    metadata: dict[str, Any] | None = None,
) -> ToolResult:
    payload = {"error": {"type": error_type, "message": message, "retryable": retryable}}
    return ToolResult(
        success=False,
        content=_json(payload),
        error=message,
        metadata={**(metadata or {}), "error_type": error_type, "retryable": retryable},
    )


def _search_url(base: str) -> str:
    base = base.strip().rstrip("/") + "/"
    return urljoin(base, "search")


def _normalize_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text or "").strip()


def _safe_extension(content_type: str | None) -> str:
    if not content_type:
        return ".bin"
    mime = content_type.split(";", 1)[0].strip()
    ext = mimetypes.guess_extension(mime) or ".bin"
    return ext if ext.startswith(".") else f".{ext}"


class _HTMLExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._current_href: str | None = None
        self._current_link_text: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip_depth += 1
            return
        if tag == "a":
            href = ""
            for key, value in attrs:
                if key.lower() == "href" and value:
                    href = value
                    break
            self._current_href = href or None
            self._current_link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if tag == "a" and self._current_href:
            text = _normalize_text(" ".join(self._current_link_text))
            self.links.append({"href": self._current_href, "text": text})
            self._current_href = None
            self._current_link_text = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if not data:
            return
        if self._current_href is not None:
            self._current_link_text.append(data)
        self.text_parts.append(data)


class BuiltinWebSearchTool(BaseTool):
    name = "search"
    description = "Search the web using SearXNG."
    server_id = "web"
    risk_level = "read"
    tool_requires_network = True
    emits_artifacts = False

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "top_k": {
                    "type": "integer",
                    "description": "Maximum number of results to return",
                    "default": get_config().search.default_results,
                    "minimum": 1,
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, top_k: int | None = None, **kwargs: Any) -> ToolResult:
        config = get_config().search
        limit = int(top_k or config.default_results)
        if limit <= 0:
            return _error_result(
                error_type="InvalidArgument",
                message="top_k must be >= 1",
                retryable=False,
            )

        params = {
            "q": query,
            "format": "json",
            "language": "en",
            "safesearch": 0,
        }
        transport = kwargs.get("transport")
        try:
            async with httpx.AsyncClient(timeout=config.timeout, transport=transport) as client:
                response = await client.get(_search_url(config.searxng_url), params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            return _error_result(
                error_type="Timeout",
                message=f"SearXNG search timed out: {exc}",
                retryable=True,
            )
        except httpx.RequestError as exc:
            return _error_result(
                error_type="NetworkError",
                message=f"SearXNG search failed: {exc}",
                retryable=True,
            )
        except httpx.HTTPStatusError as exc:
            retryable = exc.response.status_code >= 500
            return _error_result(
                error_type="HttpError",
                message=f"SearXNG search returned {exc.response.status_code}",
                retryable=retryable,
                metadata={"status_code": exc.response.status_code},
            )
        except Exception as exc:
            return _error_result(
                error_type="UnknownError",
                message=f"SearXNG search error: {exc}",
                retryable=False,
            )

        raw_results = payload.get("results") if isinstance(payload, dict) else []
        results: list[dict[str, Any]] = []
        for index, item in enumerate(raw_results[:limit], start=1):
            if not isinstance(item, dict):
                continue
            results.append(
                {
                    "rank": index,
                    "title": str(item.get("title") or ""),
                    "url": str(item.get("url") or ""),
                    "snippet": str(item.get("content") or item.get("snippet") or ""),
                }
            )

        results = sorted(results, key=lambda entry: entry["rank"])
        data = {"query": query, "results": results}
        return ToolResult(
            success=True,
            content=_json({"data": data}),
            metadata={"query": query, "results": results, "result_count": len(results)},
        )


class BuiltinWebFetchTool(BaseTool):
    name = "fetch"
    description = "Fetch a URL and store the response as an artifact."
    server_id = "web"
    risk_level = "read"
    tool_requires_network = True
    emits_artifacts = True

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "max_bytes": {
                    "type": "integer",
                    "description": "Maximum bytes to read",
                    "minimum": 1,
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Timeout in seconds",
                    "minimum": 1,
                },
            },
            "required": ["url"],
        }

    async def execute(
        self,
        url: str,
        max_bytes: int | None = None,
        timeout_seconds: int | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        config = get_config().search
        hard_cap = int(config.fetch_max_bytes)
        requested = int(max_bytes or config.fetch_max_bytes)
        byte_limit = min(requested, hard_cap)
        timeout = int(timeout_seconds or config.fetch_timeout_seconds)
        transport = kwargs.get("transport")

        workspace = kwargs.get("workspace")
        if workspace is None:
            return _error_result(
                error_type="WorkspaceMissing",
                message="Workspace is required to store artifacts.",
                retryable=False,
            )

        try:
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=True, transport=transport
            ) as client:
                async with client.stream("GET", url) as response:
                    content_type = response.headers.get("content-type")
                    chunks: list[bytes] = []
                    bytes_read = 0
                    truncated = False
                    async for chunk in response.aiter_bytes():
                        if not chunk:
                            continue
                        remaining = byte_limit - bytes_read
                        if remaining <= 0:
                            truncated = True
                            break
                        if len(chunk) > remaining:
                            chunks.append(chunk[:remaining])
                            bytes_read += remaining
                            truncated = True
                            break
                        chunks.append(chunk)
                        bytes_read += len(chunk)
                    body = b"".join(chunks)
                    status_code = response.status_code
                    redirects = [
                        {"url": str(resp.url), "status_code": resp.status_code}
                        for resp in response.history[: config.fetch_max_redirects]
                    ]
        except httpx.TimeoutException as exc:
            return _error_result(
                error_type="Timeout",
                message=f"Fetch timed out: {exc}",
                retryable=True,
            )
        except httpx.RequestError as exc:
            return _error_result(
                error_type="NetworkError",
                message=f"Fetch failed: {exc}",
                retryable=True,
            )
        except Exception as exc:
            return _error_result(
                error_type="UnknownError",
                message=f"Fetch error: {exc}",
                retryable=False,
            )

        artifact_dir = Path(workspace.artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
        extension = _safe_extension(content_type)
        artifact_path = artifact_dir / f"web_fetch_{digest}{extension}"
        artifact_path.write_bytes(body)

        registry = ArtifactRegistry(artifact_dir)
        record = registry.register_file(
            artifact_path,
            description=f"Fetched content from {url}",
            source=url,
            extra={
                "type": "file",
                "name": artifact_path.name,
                "mime_type": content_type,
                "size_bytes": bytes_read,
            },
        )

        data = {
            "url": url,
            "status_code": status_code,
            "content_type": content_type,
            "bytes_read": bytes_read,
            "truncated": truncated,
            "artifact_ref": str(artifact_path),
        }
        meta = {"redirects": redirects}
        return ToolResult(
            success=True,
            content=_json({"data": data, "meta": meta}),
            metadata={**data, "redirects": redirects},
            artifacts=[
                {
                    "path": record.get("path"),
                    "type": record.get("type") or "file",
                    "name": record.get("name") or artifact_path.name,
                    "description": record.get("description") or "Fetched web content",
                    "source": record.get("source") or url,
                }
            ],
        )


class BuiltinWebExtractTool(BaseTool):
    name = "extract"
    description = "Extract text or links from a fetched web artifact."
    server_id = "web"
    risk_level = "read"
    tool_requires_network = False
    emits_artifacts = False
    path_params = ("artifact_ref",)
    uses_filesystem_paths = True

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "artifact_ref": {"type": "string", "description": "Artifact reference path"},
                "mode": {
                    "type": "string",
                    "description": "Extraction mode",
                    "enum": ["text", "links"],
                    "default": "text",
                },
            },
            "required": ["artifact_ref"],
        }

    async def execute(
        self,
        artifact_ref: str,
        mode: str = "text",
        **kwargs: Any,
    ) -> ToolResult:
        workspace = kwargs.get("workspace")
        try:
            resolved = resolve_and_validate_path(
                artifact_ref,
                workspace=workspace,
                allowed_paths=kwargs.get("allowed_paths"),
                denied_paths=kwargs.get("denied_paths"),
            )
        except Exception as exc:
            return _error_result(
                error_type="PathError",
                message=f"Artifact path invalid: {exc}",
                retryable=False,
            )
        if not resolved.exists():
            return _error_result(
                error_type="NotFound",
                message=f"Artifact not found: {artifact_ref}",
                retryable=False,
            )

        raw = resolved.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        parser = _HTMLExtractor()
        parser.feed(text)
        parser.close()

        if mode == "links":
            links = [link for link in parser.links if link.get("href")]
            max_links = get_config().search.extract_max_links
            truncated = len(links) > max_links
            links = links[:max_links]
            data = {"artifact_ref": str(resolved), "links": links, "truncated": truncated}
            return ToolResult(success=True, content=_json({"data": data}), metadata=data)

        extracted = _normalize_text(" ".join(parser.text_parts))
        max_chars = get_config().search.extract_max_chars
        truncated = len(extracted) > max_chars
        if truncated:
            extracted = extracted[:max_chars]
        data = {"artifact_ref": str(resolved), "text": extracted, "truncated": truncated}
        return ToolResult(success=True, content=_json({"data": data}), metadata=data)
