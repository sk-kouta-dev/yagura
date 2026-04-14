"""RAG-backed SecurityPolicyProvider.

Given a proposed DESTRUCTIVE/INSTALL operation, this provider queries a
RAG endpoint (any server returning `{"hits": [{"text": ..., "score": ...}]}`)
for matching security policy documents, then:

  1. Aggregates the top-k hits into a policy context string.
  2. Returns `PolicyCheckResult` reflecting whether the retrieved policy
     permits the operation, and whether admin approval is needed.

This is a reference implementation. Replace the scoring logic with your
policy engine of choice (OPA, Cedar, a classifier, a second LLM, etc.).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from yagura.safety.policy import PolicyCheckResult, SecurityPolicyProvider
from yagura.safety.rules import DangerLevel


class RAGSecurityPolicyProvider(SecurityPolicyProvider):
    def __init__(
        self,
        rag_endpoint: str | None = None,
        policy_filter: dict[str, Any] | None = None,
        top_k: int = 5,
        block_keywords: tuple[str, ...] = ("prohibited", "禁止", "forbidden"),
        admin_keywords: tuple[str, ...] = ("admin approval", "管理者承認", "privileged"),
        timeout: float = 5.0,
    ) -> None:
        self.rag_endpoint = rag_endpoint or os.environ.get("YAGURA_RAG_ENDPOINT", "")
        self.policy_filter = policy_filter or {"type": "security_policy"}
        self.top_k = top_k
        self.block_keywords = block_keywords
        self.admin_keywords = admin_keywords
        self.timeout = timeout

    async def check(
        self,
        tool_name: str,
        params: dict[str, Any],
        danger_level: DangerLevel,
    ) -> PolicyCheckResult:
        if not self.rag_endpoint:
            # Fail closed: with no policy source, reject DESTRUCTIVE/INSTALL.
            return PolicyCheckResult(
                allowed=False,
                reason="RAG endpoint not configured — denying by default.",
                requires_admin_approval=True,
            )
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.rag_endpoint,
                    json={
                        "query": f"{tool_name} {danger_level.name} {_short_params(params)}",
                        "filter": self.policy_filter,
                        "top_k": self.top_k,
                    },
                )
                response.raise_for_status()
                hits = response.json().get("hits", [])
        except httpx.HTTPError as exc:
            # Fail closed on RAG outage for destructive operations.
            return PolicyCheckResult(
                allowed=False,
                reason=f"RAG query failed: {exc!s}",
                requires_admin_approval=True,
            )

        text = "\n".join(hit.get("text", "") for hit in hits).lower()
        blocked = any(k.lower() in text for k in self.block_keywords)
        admin = any(k.lower() in text for k in self.admin_keywords)

        if blocked:
            return PolicyCheckResult(
                allowed=False,
                reason=f"Policy match prohibits '{tool_name}' ({danger_level.name}).",
                requires_admin_approval=True,
            )
        return PolicyCheckResult(
            allowed=True,
            reason=f"Policy review ({len(hits)} hits) passed.",
            requires_admin_approval=admin or danger_level is DangerLevel.INSTALL,
        )


def _short_params(params: dict[str, Any], limit: int = 256) -> str:
    import json

    text = json.dumps(params, ensure_ascii=False, default=str)
    return text[:limit] + ("…" if len(text) > limit else "")
