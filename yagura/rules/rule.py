"""Rule dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from yagura.rules.triggers import RuleTrigger


@dataclass
class Rule:
    """An automated workflow: a trigger + a plan template (natural language)."""

    name: str
    trigger: RuleTrigger
    plan_template: str
    id: str = field(default_factory=lambda: str(uuid4()))
    enabled: bool = True
    created_by: str = "default"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
