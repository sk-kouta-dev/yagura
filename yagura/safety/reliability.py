"""Reliability levels for information from external tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ReliabilityLevel(Enum):
    """Trustworthiness of a piece of information retrieved by a tool."""

    AUTHORITATIVE = "authoritative"
    VERIFIED = "verified"
    REFERENCE = "reference"


@dataclass
class SearchResult:
    """A single piece of retrieved content with a reliability tag."""

    content: str
    source: str
    reliability: ReliabilityLevel = ReliabilityLevel.AUTHORITATIVE
    metadata: dict[str, Any] = field(default_factory=dict)
