# Changelog

## 0.1.1 (2026-04-15)

### Security
- Layer 3 low-confidence escalation: when fallback LLM confidence is below threshold, automatically escalate to DESTRUCTIVE and force human confirmation regardless of auto_execute_threshold setting

### Ecosystem
- Remaining 7 packages published at 0.1.0: yagura-tools-llm, yagura-tools-microsoft, yagura-tools-notion, yagura-tools-openapi, yagura-tools-scraping, yagura-tools-slack, yagura-tools-snowflake. All 26 ecosystem packages are now on PyPI.

## 0.1.0 (2026-04-14)

Initial release.

### Core Framework

- Agent with Plan generation, confirmation, and execution
- 3-layer DangerAssessor (rule-based → LLM → fallback)
- Plan state machine (8 states, 15+ transitions)
- Auto-execute threshold (configurable per DangerLevel)
- Environment-aware DangerRules (LOCAL/DOCKER/SANDBOX/SERVER/REMOTE)
- StepContext with `$step_N` reference resolution (Phase A direct + Phase B LLM fallback)
- Static and Dynamic Tool support (`requires_llm` flag)
- LLM-as-tool execution path (`llm_task_template`) — explicit prompt, no params convention
- LLMRouter for data-attribute-based LLM selection
- Reliability Model (AUTHORITATIVE / VERIFIED / REFERENCE)
- Session management with atomic concurrency control
- Pause / Resume support
- Conversational memory (Session.history → Planner system prompt)
- Streaming (9 event types, async iterator)
- OpenTelemetry tracing (opt-in)
- LLM retry with exponential backoff (max 3)
- 5 safety presets (`development` / `sandbox` / `internal_tool` / `enterprise` / `maximum_security`)
- 3 built-in LLM providers (Anthropic / OpenAI / Ollama)
- 2 built-in state stores (InMemory / SQLite)
- Rule Engine with CronTrigger / FileWatchTrigger / WebhookTrigger

### Ecosystem (26 packages, 188+ tools)

- **Tools**: `yagura-tools-common`, `-aws`, `-gcp`, `-azure`, `-slack`, `-google`, `-microsoft`, `-git`, `-db`, `-browser`, `-docker`, `-k8s`, `-notion`, `-jira`, `-confluence`, `-datadog`, `-snowflake`, `-openapi`, `-scraping`, `-llm`
- **State stores**: `yagura-state-postgres`, `-redis`, `-dynamodb`
- **Loggers**: `yagura-logger-datadog`, `-cloudwatch`
- **Auth**: `yagura-auth-oauth2`

### Starter Templates (7)

- `chatbot`, `filemanager`, `devops`, `office`, `data`, `browser`, `enterprise`

### Test Coverage

- 286 tests passing (unit + ecosystem integration + starter e2e)
