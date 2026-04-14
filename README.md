# 🏯 Yagura

**Safety-native AI agent framework. Define tools, Yagura handles the rest.**

[![PyPI](https://img.shields.io/pypi/v/yagura-agent)](https://pypi.org/project/yagura-agent/)
[![Python](https://img.shields.io/pypi/pyversions/yagura-agent)](https://pypi.org/project/yagura-agent/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-286%20passing-brightgreen)]()

## What is Yagura?

Yagura (櫓) is a Japanese watchtower — the castle's eyes and shield. This framework brings the same philosophy to AI agents: every tool invocation passes through a multi-layered safety assessment before execution. Safety is not an add-on. It's built into the execution loop.

## Key Features

- **3-Layer DangerAssessor** — Rule-based (zero cost, instant) → LLM assessment → Fallback LLM. 90% of operations assessed without any LLM call.
- **Plan Confirmation with Auto-Execute** — Configurable threshold: READ-only plans auto-execute, dangerous operations require user approval.
- **Environment-Aware Safety** — Same tool, different danger levels in LOCAL vs DOCKER vs SERVER. Automatic adjustment.
- **Zero Built-in Tools** — Pure infrastructure. What the agent does is 100% defined by you.
- **Provider Pattern Everywhere** — LLM, State Store, Logger, Auth, Transport, Confirmation — all swappable.
- **Dynamic LLM Routing** — Route confidential data to local LLM, general data to cloud API. Per-step, automatic.
- **Streaming** — 9 event types. Real-time plan progress via async iterator or WebSocket.
- **OpenTelemetry** — Opt-in tracing for every plan, step, and LLM call. Zero overhead when disabled.
- **26 Ecosystem Packages** — 188+ pre-built tools for AWS, GCP, Azure, Slack, Google Workspace, Microsoft 365, Docker, Kubernetes, databases, and more.
- **5 Safety Presets + 7 Starter Templates** — From `development()` to `maximum_security()`. From chatbot to enterprise FastAPI stack.

## Install

```bash
pip install yagura-agent
```

## Quick Start

```python
import asyncio
from yagura import Agent, Config, Tool, DangerLevel
from yagura.llm import AnthropicProvider

def list_files(directory: str) -> list[str]:
    import os
    return os.listdir(directory)

agent = Agent(config=Config(
    planner_llm=AnthropicProvider(model="claude-sonnet-4-20250514")
))

agent.register_tool(Tool(
    name="list_files",
    description="List files in a directory",
    parameters={
        "type": "object",
        "properties": {
            "directory": {"type": "string", "description": "Path to directory"}
        },
        "required": ["directory"]
    },
    handler=list_files,
    danger_level=DangerLevel.READ,
))

response = asyncio.run(agent.run("What files are in my home directory?"))
print(response.plan)
```

10 lines to a working agent with full safety assessment.

## Why Yagura?

| Feature | Yagura | LangChain | CrewAI | Google ADK | MS Agent FW |
|---------|--------|-----------|--------|------------|-------------|
| Safety in execution loop | ✅ Native | ❌ Add-on | ❌ None | ⚠️ Callback | ❌ User-built |
| DangerLevel per tool | ✅ 4 levels | ❌ | ❌ | ❌ | ❌ |
| Plan confirmation | ✅ Threshold | ❌ | ❌ | ⚠️ Per-tool HITL | ❌ |
| Environment-aware danger | ✅ 5 envs | ❌ | ❌ | ❌ | ❌ |
| Multi-agent | ❌ Single | ✅ | ✅ | ✅ | ✅ |
| GUI builder | ❌ | ⚠️ LangFlow | ❌ | ✅ ADK Web UI | ❌ |
| Streaming | ✅ | ✅ | ⚠️ Limited | ✅ | ✅ |
| Multi-language | ❌ Python only | ✅ Py/TS | ✅ Py/TS | ✅ Py/TS/Go/Java | ✅ Py/.NET |
| Ecosystem size | 26 pkg / 188 tools | 100+ integrations | 20+ tools | Google Cloud native | Azure native |
| Observability | ✅ OpenTelemetry | ✅ LangSmith | ⚠️ Limited | ✅ Cloud Trace | ✅ OTel |

## Safety Presets

```python
from yagura import Config
from yagura.presets import safety_presets

# One line to configure safety for your use case
config = Config(planner_llm=my_llm, **safety_presets.enterprise())
```

| Preset | Auto-Execute | Environment | Use Case |
|--------|-------------|-------------|----------|
| `development()` | MODIFY and below | LOCAL | Local dev and testing |
| `sandbox()` | Everything | SANDBOX | Demos and workshops |
| `internal_tool()` | READ only | LOCAL | Internal company tools |
| `enterprise()` | Nothing (all confirm) | SERVER | Production multi-user |
| `maximum_security()` | Nothing + policy required | SERVER | Regulated industries |

## Ecosystem

```bash
pip install yagura-tools-common    # Shell, file ops, HTTP (13 tools)
pip install yagura-tools-aws       # S3, Lambda, SQS, Bedrock (12 tools)
pip install yagura-tools-google    # Gmail, Drive, Calendar, Sheets (15 tools)
pip install yagura-tools-slack     # Messages, channels, files (7 tools)
pip install yagura-tools-db        # PostgreSQL, MySQL, SQLite + NL→SQL (4 tools)
# ... and 21 more packages
```

<details>
<summary><b>All 26 Ecosystem Packages</b></summary>

| Package | Tools | Description |
|---------|-------|-------------|
| yagura-tools-common | 13 | Shell, file, directory, HTTP, process |
| yagura-tools-aws | 12 | S3, Lambda, SQS, Step Functions, Bedrock |
| yagura-tools-gcp | 7 | GCS, BigQuery, Cloud Functions |
| yagura-tools-azure | 8 | Blob Storage, Functions, Cosmos DB |
| yagura-tools-slack | 7 | Messages, channels, reactions, files |
| yagura-tools-google | 15 | Gmail, Drive, Calendar, Sheets |
| yagura-tools-microsoft | 14 | Outlook, OneDrive, SharePoint, Teams |
| yagura-tools-git | 12 | Commit, push, PR, branch, diff |
| yagura-tools-db | 4 | SQL query, NL→SQL, schema discovery |
| yagura-tools-browser | 11 | Playwright: navigate, click, fill, screenshot |
| yagura-tools-docker | 10 | Containers, images, exec, logs |
| yagura-tools-k8s | 14 | Pods, deployments, services, ConfigMaps |
| yagura-tools-notion | 10 | Pages, databases, blocks |
| yagura-tools-jira | 10 | Issues, sprints, transitions, comments |
| yagura-tools-confluence | 8 | Pages, spaces, attachments |
| yagura-tools-datadog | 8 | Metrics, alerts, dashboards, events |
| yagura-tools-snowflake | 7 | SQL, stages, Cortex, NL→SQL |
| yagura-tools-openapi | 3 | Auto-generate tools from OpenAPI specs |
| yagura-tools-scraping | 7 | Web scrape, PDF extract, OCR |
| yagura-tools-llm | 8 | Summarize, translate, extract, classify |
| yagura-state-postgres | — | PostgreSQL session store |
| yagura-state-redis | — | Redis session store with TTL |
| yagura-state-dynamodb | — | DynamoDB session store |
| yagura-logger-datadog | — | Datadog audit logger |
| yagura-logger-cloudwatch | — | CloudWatch audit logger |
| yagura-auth-oauth2 | — | OAuth2/OIDC auth provider |

</details>

## Starter Templates

```bash
git clone https://github.com/sk-kouta-dev/yagura
cd yagura/starters/chatbot
pip install -r requirements.txt
python main.py
```

| Starter | Preset | Tools | Description |
|---------|--------|-------|-------------|
| chatbot | development | common | Basic CLI agent |
| filemanager | internal_tool | common + scraping | File operations + PDF/OCR |
| devops | enterprise | docker + k8s + git | Container and deployment management |
| office | internal_tool | google + slack | Email, calendar, drive, notifications |
| data | internal_tool | db + snowflake + llm | SQL analysis + NL→SQL |
| browser | development | browser + scraping | Web automation |
| enterprise | enterprise | Full stack | FastAPI + OAuth2 + Postgres + Datadog |

## Architecture

```
User Input → Planner (LLM) → Plan
                                ↓
                          PlanExecutor
                           For each step:
                            ├─ DangerAssessor (3-layer)
                            ├─ User Confirmation (if needed)
                            └─ ToolExecutor → Result
```

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
