# yagura-starter-enterprise

Production-ready Yagura deployment. FastAPI + WebSocket + full safety stack.

## What ships in here

| Layer | Component |
|---|---|
| HTTP / WebSocket | FastAPI with bearer-token auth |
| Planner LLM | Anthropic Claude (`claude-sonnet-4-20250514`) |
| Executor LLM | Ollama (`qwen2.5:7b`) — runs locally for confidential data |
| Fallback LLM | Anthropic Claude (DangerAssessor Layer 3) |
| State store | `PostgresStateStore` (JSONB + GSI on user_id) |
| Audit log | `DatadogLogger` (v2 Logs API) |
| Auth | `OAuth2Provider` (Azure AD / Google / Okta / Auth0 / Keycloak) |
| Security policy | `RAGSecurityPolicyProvider` — queries a RAG endpoint, fails closed |
| LLM routing | `ConfidentialRouter` — routes sensitive data to local LLM |
| Tools | Google Workspace + Slack + DB + minimal common |
| Safety preset | `enterprise` + READ auto-execute, 50 concurrent sessions |

The pieces are all wired up in `config.py`. Flip
`safety_presets.enterprise(...)` → `safety_presets.maximum_security(...)`
and uncomment the `validate_maximum_security(config)` call to switch
into single-session, confirmation-on-every-plan mode.

## Quick start (Docker Compose)

```bash
cp .env.example .env
# Fill in ANTHROPIC_API_KEY, DATADOG_*, OAUTH_*, etc.
docker compose up -d postgres redis ollama
docker compose up -d app
curl http://localhost:8080/v1/healthz
```

## Quick start (local)

```bash
pip install -r requirements.txt
cp .env.example .env
# Start Postgres + Ollama yourself, then:
export $(cat .env | xargs)
python main.py
```

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/run` | Submit a prompt. Returns a plan (if confirmation needed) or result. |
| `POST` | `/v1/confirm/{session_id}` | Approve/cancel a pending plan. |
| `GET` | `/v1/sessions/{session_id}` | Fetch session + plan state. |
| `GET` | `/v1/healthz` | Liveness probe. |
| `GET` | `/v1/readyz` | Readiness probe (pings the state store). |
| `WS` | `/v1/ws/{session_id}` | Streaming chat with `kind: "run" | "confirm"` messages. |

All endpoints except `/v1/healthz` and `/v1/readyz` require
`Authorization: Bearer <token>`. Tokens are validated against the
configured OIDC issuer's JWKS.

### Example

```bash
curl -X POST http://localhost:8080/v1/run \
     -H "Authorization: Bearer $OIDC_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"prompt": "draft an email to finance@acme.com about the invoice discrepancy"}'
```

Response:

```json
{
  "session_id": "…",
  "plan_state": "draft",
  "needs_confirmation": true,
  "steps": [
    {"step_number": 1, "description": "Search recent invoices",
     "danger_level": "READ", "status": "pending", "tool_name": "gmail_search"},
    {"step_number": 2, "description": "Create an email draft",
     "danger_level": "MODIFY", "status": "pending", "tool_name": "gmail_draft_create"}
  ]
}
```

```bash
curl -X POST http://localhost:8080/v1/confirm/<session_id> \
     -H "Authorization: Bearer $OIDC_TOKEN" \
     -d '{"approved": true}'
```

## Customization hooks

- **`security_policy.py`** — swap `RAGSecurityPolicyProvider` for an OPA
  / Cedar implementation, or tighten the `block_keywords` list.
- **`llm_routing.py`** — customize `confidential_patterns`, add regex
  rules, or inject metadata-based routing (e.g. `params["tenant"] ==
  "acme-secret"`).
- **`tools.py`** — add tool packs per team (finance vs ops). Each team
  can get their own `Agent` instance sharing the same state store.
- **Swap Postgres for DynamoDB**: replace `PostgresStateStore` with
  `DynamoDBStateStore`. No other change needed.
- **Swap Datadog for CloudWatch**: replace `DatadogLogger` with
  `CloudWatchLogger`.

## Production checklist

- [ ] Lock down `CORSMiddleware.allow_origins` to your frontend.
- [ ] Set `OAUTH_AUDIENCE` explicitly to reject tokens issued for other
      apps.
- [ ] Front with a reverse proxy (Caddy / nginx / ALB) for TLS.
- [ ] Configure Postgres backups; audit logs live in Datadog but
      session state lives in Postgres.
- [ ] Configure a Datadog dashboard reading `service:yagura-enterprise`
      logs — pre-built JSON available in the `yagura-logger-datadog`
      package docs.
- [ ] Set Kubernetes liveness/readiness probes to `/v1/healthz` and
      `/v1/readyz`.
