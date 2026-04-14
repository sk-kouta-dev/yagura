"""ConfidentialRouter — route Dynamic Tool calls by data sensitivity.

Sensitive parameters (paths matching `confidential_patterns` or values
matching `confidential_regex`) → local LLM. Everything else → cloud LLM.

Falls back to the cloud LLM when no confidential signal is found.
"""

from __future__ import annotations

import re
from typing import Any

from yagura.llm.provider import LLMProvider, LLMRouter
from yagura.plan import StepContext
from yagura.tools.tool import Tool


class ConfidentialRouter(LLMRouter):
    def __init__(
        self,
        local_llm: LLMProvider,
        cloud_llm: LLMProvider,
        confidential_patterns: list[str] | None = None,
        confidential_regex: str | None = None,
    ) -> None:
        self.local_llm = local_llm
        self.cloud_llm = cloud_llm
        self.confidential_patterns = confidential_patterns or [
            "/confidential/",
            "/機密/",
            "/internal-only/",
            "/restricted/",
        ]
        self.confidential_regex = (
            re.compile(confidential_regex) if confidential_regex else None
        )

    async def select(
        self,
        tool: Tool,
        params: dict[str, Any],
        context: StepContext,
    ) -> LLMProvider:
        if self._is_confidential(params):
            return self.local_llm
        return self.cloud_llm

    def _is_confidential(self, value: Any) -> bool:
        if isinstance(value, str):
            if any(pattern in value for pattern in self.confidential_patterns):
                return True
            if self.confidential_regex and self.confidential_regex.search(value):
                return True
            return False
        if isinstance(value, dict):
            return any(self._is_confidential(v) for v in value.values())
        if isinstance(value, list):
            return any(self._is_confidential(v) for v in value)
        return False
