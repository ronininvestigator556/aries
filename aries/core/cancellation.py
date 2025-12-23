"""
Cancellation primitives for Aries.
"""

import asyncio


class CancellationToken:
    """A thread-safe cancellation token."""

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._cancelled = False

    def cancel(self) -> None:
        """Request cancellation."""
        self._cancelled = True
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._cancelled

    async def wait(self) -> None:
        """Wait until cancellation is requested."""
        await self._event.wait()
