"""Build the enterprise Agent.

Stack:
  - AnthropicProvider (Claude) as planner.
  - OllamaProvider (qwen2.5-7b) as local executor for confidential data.
  - AnthropicProvider as fallback_llm (DangerAssessor Layer 3).
  - PostgresStateStore for multi-user session persistence.
  - DatadogLogger for centralized audit.
  - OAuth2Provider against an OIDC issuer (Azure AD, Okta, Google, etc.).
  - RAGSecurityPolicyProvider for DESTRUCTIVE/INSTALL gating.
  - ConfidentialRouter for confidential-data LLM selection.

Every field is configurable via `.env`; see `.env.example`.
"""

from __future__ import annotations

import os

from yagura import Agent, Config, DangerLevel, safety_presets
from yagura.llm import AnthropicProvider, OllamaProvider
from yagura.presets.safety import validate_maximum_security
from yagura_auth.oauth2 import OAuth2Provider
from yagura_logger.datadog import DatadogLogger
from yagura_state.postgres import PostgresStateStore

from llm_routing import ConfidentialRouter
from security_policy import RAGSecurityPolicyProvider
from tools import all_tools


def build_agent() -> Agent:
    planner = AnthropicProvider(
        model=os.environ.get("YAGURA_PLANNER_MODEL", "claude-sonnet-4-20250514"),
        api_key=os.environ["ANTHROPIC_API_KEY"],
    )
    local_executor = OllamaProvider(
        model=os.environ.get("YAGURA_EXECUTOR_MODEL", "qwen2.5:7b"),
        host=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
    )
    fallback = AnthropicProvider(
        model=os.environ.get("YAGURA_FALLBACK_MODEL", "claude-sonnet-4-20250514"),
        api_key=os.environ["ANTHROPIC_API_KEY"],
    )

    config = Config(
        planner_llm=planner,
        executor_llm=local_executor,
        fallback_llm=fallback,
        **{
            **safety_presets.enterprise(
                api_keys={},
                max_concurrent_sessions=int(os.environ.get("YAGURA_MAX_SESSIONS", "50")),
            ),
            # Allow READ plans to auto-execute so inbox search / dashboards are snappy.
            "auto_execute_threshold": DangerLevel.READ,
            "security_policy_provider": RAGSecurityPolicyProvider(
                rag_endpoint=os.environ.get("YAGURA_RAG_ENDPOINT", ""),
                policy_filter={"type": "security_policy"},
            ),
            "llm_router": ConfidentialRouter(
                local_llm=local_executor,
                cloud_llm=planner,
                confidential_patterns=os.environ.get(
                    "YAGURA_CONFIDENTIAL_PATTERNS", "/confidential/,/機密/,/internal-only/"
                ).split(","),
            ),
            "state_store": PostgresStateStore(
                connection_string=os.environ["POSTGRES_URL"],
                table_name=os.environ.get("POSTGRES_TABLE", "yagura_sessions"),
            ),
            "logger": DatadogLogger(
                api_key=os.environ["DATADOG_API_KEY"],
                app_key=os.environ.get("DATADOG_APP_KEY"),
                service=os.environ.get("DATADOG_SERVICE", "yagura-enterprise"),
                env=os.environ.get("DATADOG_ENV", "production"),
                site=os.environ.get("DATADOG_SITE", "datadoghq.com"),
            ),
            "auth_provider": OAuth2Provider(
                issuer=os.environ["OAUTH_ISSUER"],
                client_id=os.environ["OAUTH_CLIENT_ID"],
                client_secret=os.environ.get("OAUTH_CLIENT_SECRET"),
                scopes=os.environ.get(
                    "OAUTH_SCOPES", "openid profile email"
                ).split(),
                audience=os.environ.get("OAUTH_AUDIENCE"),
            ),
        },
    )

    # If you prefer the `maximum_security` preset instead (stricter —
    # every plan confirms, single concurrent session, no READ auto-execute),
    # swap the `enterprise(...)` call above for `maximum_security(...)` and
    # uncomment the following validation:
    #
    #     validate_maximum_security(config)

    agent = Agent(config=config)
    agent.register_tools(all_tools)
    return agent
