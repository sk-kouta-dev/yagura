"""TransportClient ABC — connects to a remote backend."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any


class TransportClient(ABC):
    """Client-side transport for connecting to a remote Yagura backend."""

    @abstractmethod
    async def connect(self, url: str) -> None:
        """Establish the connection to the remote backend."""

    @abstractmethod
    async def send(self, message: dict[str, Any]) -> None:
        """Send a message (tool invocation, status update, etc.) to the backend."""

    @abstractmethod
    async def on_message(self, handler: Callable[[dict[str, Any]], Any]) -> None:
        """Register a handler for inbound server messages."""
