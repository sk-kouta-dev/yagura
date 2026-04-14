"""TransportServer ABC — accepts client connections."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class TransportServer(ABC):
    """Server-side transport endpoint for REMOTE or CLIENT tool dispatch."""

    @abstractmethod
    async def start(self, host: str, port: int) -> None:
        """Begin accepting connections on the given host/port."""

    @abstractmethod
    async def broadcast(self, session_id: str, message: dict[str, Any]) -> None:
        """Push a message to any clients subscribed to this session."""
