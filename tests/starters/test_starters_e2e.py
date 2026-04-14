"""Deep end-to-end tests for the starters.

Where possible, these actually execute a plan through the starter's
Agent, hitting real tools (SQLite, filesystem, subprocess). External
services (Slack, Google, Docker daemon, k8s cluster, Postgres, Datadog,
OAuth issuers) are mocked by patching the relevant SDK client factories.

The goal: catch failures that the shallow `test_starters.py` tests miss
because they only check that `build_agent()` returns an Agent.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import MockLLMProvider, plan_tool_response
from yagura import PlanState
from yagura.confirmation.handler import ConfirmationHandler
from yagura.plan import Plan, PlanConfirmation, PlanStep
from yagura.safety.assessor import DangerAssessment
from yagura.tools.tool import ToolResult

_STARTERS = Path(__file__).resolve().parent.parent.parent / "starters"
_SHARED = _STARTERS / "_shared"


class _Approve(ConfirmationHandler):
    """Approve every prompt including DESTRUCTIVE steps and REFERENCE results."""

    async def confirm_plan(self, plan: Plan) -> PlanConfirmation:
        return PlanConfirmation(approved=True)

    async def confirm_danger(self, step: PlanStep, assessment: DangerAssessment) -> bool:
        return True

    async def confirm_reference_result(self, step: PlanStep, result: ToolResult) -> bool:
        return True


def _load_starter_module(starter: str, module: str) -> Any:
    """Load a starter's module with its directory + `_shared/` on sys.path."""
    starter_path = _STARTERS / starter
    file_path = starter_path / f"{module}.py"
    restore_path = list(sys.path)
    sys.path.insert(0, str(starter_path))
    sys.path.insert(0, str(_SHARED))
    for key in ("tools", "config", "cli", "security_policy", "llm_routing"):
        sys.modules.pop(key, None)
    try:
        spec = importlib.util.spec_from_file_location(f"starter_{starter}_{module}", file_path)
        assert spec and spec.loader
        loaded = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loaded)
        return loaded
    finally:
        sys.path[:] = restore_path


def _patch_planner(monkeypatch: pytest.MonkeyPatch, mock: MockLLMProvider) -> None:
    """Replace AnthropicProvider / OllamaProvider constructors with a factory
    that returns the given MockLLMProvider — covers both planner and executor
    LLMs that starters instantiate inside config.py."""
    import yagura.llm

    monkeypatch.setattr(yagura.llm, "AnthropicProvider", lambda *a, **k: mock)
    monkeypatch.setattr(yagura.llm, "OllamaProvider", lambda *a, **k: mock)


async def _run_and_confirm(agent, user_input: str):
    """Run a plan and, if confirmation is required (the default for most
    presets), auto-approve it. This mirrors what `starters/_shared/cli.py`
    does when the user types 'y' at the prompt."""
    response = await agent.run(user_input)
    if response.needs_confirmation:
        response = await agent.confirm(
            response.session.id,
            PlanConfirmation(approved=True),
        )
    return response


# ---------------------------------------------------------------------------
# chatbot — 5 common tools, development preset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chatbot_e2e_runs_directory_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")

    mock = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "directory_list",
                        "parameters": {"path": str(tmp_path)},
                        "description": "list files",
                    }
                ]
            )
        ]
    )
    _patch_planner(monkeypatch, mock)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.chdir(tmp_path)

    config_mod = _load_starter_module("chatbot", "config")
    agent = config_mod.build_agent()
    # development preset auto-approves MODIFY, but directory_list is READ —
    # still need to swap handler to avoid the REFERENCE-reliability prompt.
    agent.confirmation_handler = _Approve()

    response = await agent.run("list files here")
    assert response.plan.state is PlanState.COMPLETED
    step = response.plan.steps[0]
    assert step.tool_name == "directory_list"
    assert step.result.data["count"] == 2


@pytest.mark.asyncio
async def test_chatbot_e2e_runs_file_write_then_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two-step plan with $step_N reference: write then read the same file."""
    target = tmp_path / "hello.txt"
    mock = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "file_write",
                        "parameters": {"path": str(target), "content": "yagura works"},
                        "description": "write the file",
                    },
                    {
                        "step_number": 2,
                        "tool_name": "file_read",
                        "parameters": {"path": "$step_1.data.path"},
                        "description": "read it back",
                    },
                ]
            )
        ]
    )
    _patch_planner(monkeypatch, mock)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.chdir(tmp_path)

    config_mod = _load_starter_module("chatbot", "config")
    agent = config_mod.build_agent()
    agent.confirmation_handler = _Approve()

    response = await agent.run("write then read hello.txt")
    assert response.plan.state is PlanState.COMPLETED
    assert response.plan.steps[1].result.data["content"] == "yagura works"
    assert target.read_text(encoding="utf-8") == "yagura works"


# ---------------------------------------------------------------------------
# filemanager — common + pdf/ocr (pypdf is installed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_filemanager_e2e_copy_then_delete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "src.txt"
    src.write_text("copy me", encoding="utf-8")
    dst = tmp_path / "dst.txt"

    mock = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "file_copy",
                        "parameters": {"source": str(src), "destination": str(dst)},
                        "description": "copy file",
                    },
                    {
                        "step_number": 2,
                        "tool_name": "file_delete",
                        "parameters": {"path": str(src)},
                        "description": "delete source",
                    },
                ]
            )
        ]
    )
    _patch_planner(monkeypatch, mock)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.chdir(tmp_path)

    config_mod = _load_starter_module("filemanager", "config")
    agent = config_mod.build_agent(audit_path=str(tmp_path / "audit.jsonl"))
    # internal_tool preset: MODIFY and DESTRUCTIVE need confirmation → approve.
    agent.confirmation_handler = _Approve()

    response = await _run_and_confirm(agent, "move src to dst then delete src")
    assert response.plan.state is PlanState.COMPLETED
    assert dst.exists()
    assert not src.exists()
    # Audit log should have been written.
    assert (tmp_path / "audit.jsonl").exists()


@pytest.mark.asyncio
async def test_filemanager_pdf_extraction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Create a tiny real PDF with pypdf so pdf_extract_text has something to read.
    import pypdf

    pdf_path = tmp_path / "note.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with pdf_path.open("wb") as f:
        writer.write(f)

    mock = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "pdf_extract_text",
                        "parameters": {"file_path": str(pdf_path)},
                        "description": "extract pdf",
                    }
                ]
            )
        ]
    )
    _patch_planner(monkeypatch, mock)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.chdir(tmp_path)

    config_mod = _load_starter_module("filemanager", "config")
    agent = config_mod.build_agent(audit_path=str(tmp_path / "audit.jsonl"))
    agent.confirmation_handler = _Approve()

    response = await _run_and_confirm(agent, "extract pdf")
    assert response.plan.state is PlanState.COMPLETED
    # Blank page → empty text, but the tool succeeded and reported page_count=1.
    assert response.plan.steps[0].result.data["page_count"] == 1


# ---------------------------------------------------------------------------
# data — SQLite end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_data_starter_e2e_sqlite_query(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "sample.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);
            INSERT INTO users (name) VALUES ('alice'), ('bob');
            """
        )
    conn_string = f"sqlite:///{db.as_posix()}"

    from tests.conftest import assess_response
    from yagura.llm.provider import LLMResponse

    mock = MockLLMProvider(
        responses=[
            # 1. Planner: the plan.
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "db_list_tables",
                        "parameters": {"connection_string": conn_string},
                        "description": "list tables",
                    },
                    {
                        "step_number": 2,
                        "tool_name": "db_query",
                        "parameters": {
                            "connection_string": conn_string,
                            "query": "SELECT name FROM users ORDER BY name",
                        },
                        "description": "query users",
                    },
                ]
            ),
            # 2. DangerAssessor Layer 2: classify the SELECT as READ.
            #    (db_list_tables has an explicit READ level; only db_query goes
            #    through the LLM assessor.)
            assess_response("READ", confidence=0.95, reason="SELECT has no side effects"),
            # 3. _transform_params_via_llm for db_query (Dynamic Tool hook).
            LLMResponse(
                content=json.dumps(
                    {
                        "connection_string": conn_string,
                        "query": "SELECT name FROM users ORDER BY name",
                    }
                ),
                tool_calls=[],
            ),
        ]
    )
    _patch_planner(monkeypatch, mock)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.chdir(tmp_path)

    config_mod = _load_starter_module("data", "config")
    agent = config_mod.build_agent(audit_path=str(tmp_path / "audit.jsonl"))
    agent.confirmation_handler = _Approve()

    response = await _run_and_confirm(agent, "show users")
    assert response.plan.state is PlanState.COMPLETED
    assert "users" in response.plan.steps[0].result.data["tables"]
    rows = response.plan.steps[1].result.data["rows"]
    names = [r["name"] for r in rows]
    assert names == ["alice", "bob"]


@pytest.mark.asyncio
async def test_data_starter_init_db_script_creates_sample_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The data starter ships an init_db.py that must produce a valid SQLite file."""
    # Execute init_db.py in a sandboxed cwd.
    monkeypatch.chdir(tmp_path)
    # Point the script's DB_PATH relative anchor at tmp_path.
    init_script = _STARTERS / "data" / "init_db.py"
    # The script computes DB_PATH from __file__; we copy it into tmp and run.
    copied = tmp_path / "init_db.py"
    copied.write_text(init_script.read_text(encoding="utf-8"), encoding="utf-8")
    import runpy

    runpy.run_path(str(copied), run_name="__main__")
    db = tmp_path / "sample_data" / "sample.db"
    assert db.exists()
    with sqlite3.connect(db) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    assert set(tables) == {"customers", "products", "orders"}


# ---------------------------------------------------------------------------
# devops — git (real tool, no external services)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_devops_starter_git_status_on_real_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import git

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    git.Repo.init(repo_path)
    (repo_path / "README.md").write_text("# test", encoding="utf-8")

    mock = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "git_status",
                        "parameters": {"repo_path": str(repo_path)},
                        "description": "check status",
                    }
                ]
            )
        ]
    )
    _patch_planner(monkeypatch, mock)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.chdir(tmp_path)

    config_mod = _load_starter_module("devops", "config")
    agent = config_mod.build_agent(audit_path=str(tmp_path / "audit.jsonl"))
    agent.confirmation_handler = _Approve()

    response = await _run_and_confirm(agent, "show git status")
    assert response.plan.state is PlanState.COMPLETED
    data = response.plan.steps[0].result.data
    assert data["dirty"] is True  # README.md is untracked
    assert "README.md" in data["untracked"]


# ---------------------------------------------------------------------------
# office — slack_sdk installed; patch WebClient so no network hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_office_starter_slack_send_mocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Patch slack_sdk.WebClient so slack_send doesn't touch the network.
    class _FakeSlackClient:
        def __init__(self, token: str) -> None:
            self.token = token

        def chat_postMessage(self, **kwargs):
            return {"ok": True, "ts": "1234.5678", "channel": kwargs["channel"]}

    import slack_sdk

    monkeypatch.setattr(slack_sdk, "WebClient", _FakeSlackClient)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")

    mock = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "slack_send",
                        "parameters": {"channel": "#test", "text": "hello from yagura"},
                        "description": "post to slack",
                    }
                ]
            )
        ]
    )
    _patch_planner(monkeypatch, mock)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.chdir(tmp_path)

    config_mod = _load_starter_module("office", "config")
    agent = config_mod.build_agent(audit_path=str(tmp_path / "audit.jsonl"))
    agent.confirmation_handler = _Approve()

    response = await _run_and_confirm(agent, "post hello to #test")
    assert response.plan.state is PlanState.COMPLETED
    result = response.plan.steps[0].result
    assert result.success
    assert result.data["ts"] == "1234.5678"


# ---------------------------------------------------------------------------
# devops — docker (real client import, mocked daemon)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_devops_starter_docker_container_list_mocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """docker_container_list should work when the SDK is available and mocked."""
    import docker  # type: ignore

    # Build a fake docker client that returns one "container".
    class _FakeImage:
        id = "sha256:abc123abcdefg"
        tags = ["busybox:latest"]

    class _FakeContainer:
        id = "container1234567890abcdef"
        name = "sleepy"
        image = _FakeImage()
        status = "running"
        ports = {}

    class _FakeContainers:
        def list(self, all: bool = False):
            return [_FakeContainer()]

    class _FakeClient:
        containers = _FakeContainers()

    monkeypatch.setattr(docker, "from_env", lambda: _FakeClient())

    mock = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "docker_container_list",
                        "parameters": {"all": False},
                        "description": "list containers",
                    }
                ]
            )
        ]
    )
    _patch_planner(monkeypatch, mock)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.chdir(tmp_path)

    config_mod = _load_starter_module("devops", "config")
    agent = config_mod.build_agent(audit_path=str(tmp_path / "audit.jsonl"))
    agent.confirmation_handler = _Approve()

    response = await _run_and_confirm(agent, "list docker containers")
    assert response.plan.state is PlanState.COMPLETED
    data = response.plan.steps[0].result.data
    assert data["count"] == 1
    assert data["containers"][0]["name"] == "sleepy"


# ---------------------------------------------------------------------------
# browser — playwright not installed; verify the handler reports a clean error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_browser_starter_reports_missing_playwright(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without playwright installed, browser_navigate should fail with a clear message."""
    mock = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "browser_navigate",
                        "parameters": {"url": "https://example.com"},
                        "description": "navigate",
                    }
                ]
            )
        ]
    )
    _patch_planner(monkeypatch, mock)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.chdir(tmp_path)

    config_mod = _load_starter_module("browser", "config")
    agent = config_mod.build_agent()
    agent.confirmation_handler = _Approve()

    response = await agent.run("navigate")
    # The plan fails with a ToolExecutionError wrapping the ImportError.
    assert response.plan.state is PlanState.FAILED
    err = response.plan.steps[0].error or ""
    assert "playwright" in err.lower()


# ---------------------------------------------------------------------------
# enterprise — verify build_agent raises with clear env-var guidance, not a cryptic error
# ---------------------------------------------------------------------------


def test_enterprise_build_agent_reports_missing_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """enterprise/config.py requires env vars; without them, it should raise clearly."""
    # Clear all the variables the enterprise config reads.
    for var in (
        "ANTHROPIC_API_KEY",
        "OAUTH_ISSUER",
        "OAUTH_CLIENT_ID",
        "DATADOG_API_KEY",
        "POSTGRES_URL",
    ):
        monkeypatch.delenv(var, raising=False)

    config_mod = _load_starter_module("enterprise", "config")
    with pytest.raises(KeyError):
        config_mod.build_agent()


def test_enterprise_build_agent_with_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """With all required env vars + mocked LLM/state/logger, build_agent should succeed."""
    import yagura.llm

    fake_llm = MockLLMProvider()
    monkeypatch.setattr(yagura.llm, "AnthropicProvider", lambda *a, **k: fake_llm)
    monkeypatch.setattr(yagura.llm, "OllamaProvider", lambda *a, **k: fake_llm)

    # Patch expensive backends in the starter's namespace (Postgres / Datadog / OAuth2).
    # We don't want asyncpg.create_pool or a real OIDC discovery call.
    import yagura_auth.oauth2 as yao
    import yagura_logger.datadog as yld
    import yagura_state.postgres as ysp

    class _FakePostgres:
        def __init__(self, **_kwargs): ...
        async def save_session(self, *a, **k): ...
        async def load_session(self, *a, **k): ...
        async def delete_session(self, *a, **k): ...
        async def list_sessions(self, *a, **k):
            return []

        async def create_session_atomic(self, *a, **k): ...

    class _FakeDatadog:
        def __init__(self, **_kwargs): ...
        async def log_operation(self, *a, **k): ...
        async def log_assessment(self, *a, **k): ...
        async def log_plan(self, *a, **k): ...

    class _FakeOAuth2:
        def __init__(self, **_kwargs): ...
        async def authenticate(self, *a, **k):
            return None

        async def get_user_id(self, *a, **k):
            return "user"

    monkeypatch.setattr(ysp, "PostgresStateStore", _FakePostgres)
    monkeypatch.setattr(yld, "DatadogLogger", _FakeDatadog)
    monkeypatch.setattr(yao, "OAuth2Provider", _FakeOAuth2)

    for var, value in {
        "ANTHROPIC_API_KEY": "sk-test",
        "OAUTH_ISSUER": "https://example.com",
        "OAUTH_CLIENT_ID": "cid",
        "OAUTH_CLIENT_SECRET": "csec",
        "DATADOG_API_KEY": "dd",
        "POSTGRES_URL": "postgresql://test:test@localhost/test",
    }.items():
        monkeypatch.setenv(var, value)

    config_mod = _load_starter_module("enterprise", "config")
    agent = config_mod.build_agent()
    assert agent is not None
    assert len(agent.tool_registry.list_all()) > 0
