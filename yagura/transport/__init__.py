"""Transport layer interfaces for REMOTE / CLIENT execution targets.

The framework defines only the interfaces; concrete transports (WebSocket,
gRPC, SSE, REST polling, etc.) are supplied by integrators.
"""

from __future__ import annotations

from yagura.transport.client import TransportClient
from yagura.transport.server import TransportServer

__all__ = ["TransportClient", "TransportServer"]
