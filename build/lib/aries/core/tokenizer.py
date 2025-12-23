"""
Token estimation utilities with offline-friendly fallbacks.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Sequence

logger = logging.getLogger(__name__)


@dataclass
class TokenEstimator:
    """Estimate token counts with optional tiktoken support."""

    mode: str = "approx"
    encoding: str = "cl100k_base"
    approx_chars_per_token: int = 4

    def __post_init__(self) -> None:
        self._encoder = None
        self._warned = False
        self.mode = (self.mode or "approx").lower()
        if self.mode not in {"tiktoken", "approx", "disabled"}:
            self._warn_once(f"Unknown token counting mode '{self.mode}'; falling back to approximate mode.")
            self.mode = "approx"
        if self.mode == "tiktoken":
            self._encoder = self._init_tiktoken()

    def _warn_once(self, message: str) -> None:
        if self._warned:
            return
        logger.warning(message)
        self._warned = True

    def _init_tiktoken(self):
        try:
            import tiktoken  # type: ignore
        except Exception as exc:  # pragma: no cover - import failure path
            self._warn_once(f"tiktoken unavailable ({exc}); falling back to approximate token counting.")
            self.mode = "approx"
            return None

        try:
            return tiktoken.get_encoding(self.encoding)
        except Exception as exc:  # pragma: no cover - encoder failure path
            self._warn_once(
                f"Failed to initialize tiktoken encoding '{self.encoding}' ({exc}); "
                "falling back to approximate token counting."
            )
            self.mode = "approx"
            return None

    @property
    def is_disabled(self) -> bool:
        return self.mode == "disabled"

    def count(self, text: str | None) -> int:
        """Estimate token count for text."""
        if self.is_disabled or text is None:
            return 0
        if self._encoder:
            return len(self._encoder.encode(text))
        return self._approximate_count(text)

    def encode(self, text: str | None) -> list[int] | list[str]:
        """Encode text into token-like units for chunking."""
        if not text:
            return []
        if self.is_disabled:
            return [text]
        if self._encoder:
            return self._encoder.encode(text)
        return self._approximate_tokens(text)

    def decode(self, tokens: Sequence[int] | Sequence[str]) -> str:
        """Decode tokens to text."""
        if self._encoder:
            return self._encoder.decode(tokens)  # type: ignore[arg-type]
        return "".join(tokens)  # type: ignore[arg-type]

    def _approximate_count(self, text: str) -> int:
        if not text:
            return 0
        return max(1, math.ceil(len(text) / max(self.approx_chars_per_token, 1)))

    def _approximate_tokens(self, text: str) -> list[str]:
        step = max(self.approx_chars_per_token, 1)
        return [text[i : i + step] for i in range(0, len(text), step)]
