"""Starter template integration tests.

Each starter's `tools.py` is imported to verify:
  - Every declared tool is resolvable.
  - No duplicate tool names within a starter.
  - The aggregate is a non-empty list of Tool objects.

Each `config.py` is imported with a monkeypatched `AnthropicProvider`
replaced by a MockLLMProvider, so we can exercise `build_agent()`
without real API keys. We then run a tiny plan end-to-end against the
chatbot and filemanager starters.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import MockLLMProvider, plan_tool_response
from yagura.tools.tool import Tool

_STARTERS_DIR = Path(__file__).resolve().parent.parent.parent / "starters"
_SHARED_DIR = _STARTERS_DIR / "_shared"


STARTER_NAMES: list[str] = [
    "chatbot",
    "filemanager",
    "devops",
    "office",
    "data",
    "browser",
    "enterprise",
]


def _load(starter: str, module: str) -> Any:
    """Load `<starter>/<module>.py` with the starter's directory on sys.path."""
    starter_path = _STARTERS_DIR / starter
    file_path = starter_path / f"{module}.py"
    # Put the starter's own directory AND the _shared dir first so
    # their internal imports (e.g. `from cli import run_repl`) resolve.
    restore_path = list(sys.path)
    sys.path.insert(0, str(starter_path))
    sys.path.insert(0, str(_SHARED_DIR))
    # Evict previously cached modules so each starter gets its own fresh
    # `tools`, `config`, etc. namespaces.
    for key in ("tools", "config", "cli", "security_policy", "llm_routing"):
        sys.modules.pop(key, None)
    try:
        spec = importlib.util.spec_from_file_location(f"starter_{starter}_{module}", file_path)
        assert spec is not None and spec.loader is not None
        loaded = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loaded)
        return loaded
    finally:
        sys.path[:] = restore_path


# ---------------------------------------------------------------------------
# tools.py — every starter bundles real Tool objects
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("starter", [s for s in STARTER_NAMES if s != "enterprise"])
def test_tools_module_exports_all_tools(starter: str) -> None:
    tools_mod = _load(starter, "tools")
    assert hasattr(tools_mod, "all_tools")
    tools = tools_mod.all_tools
    assert isinstance(tools, list)
    assert len(tools) > 0
    assert all(isinstance(t, Tool) for t in tools)


def test_enterprise_tools_module() -> None:
    tools_mod = _load("enterprise", "tools")
    assert hasattr(tools_mod, "all_tools")
    assert all(isinstance(t, Tool) for t in tools_mod.all_tools)


@pytest.mark.parametrize("starter", STARTER_NAMES)
def test_no_duplicate_tool_names_within_starter(starter: str) -> None:
    tools_mod = _load(starter, "tools")
    seen: set[str] = set()
    for tool in tools_mod.all_tools:
        assert tool.name not in seen, f"{starter}: duplicate tool '{tool.name}'"
        seen.add(tool.name)


# ---------------------------------------------------------------------------
# Required files per starter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("starter", STARTER_NAMES)
def test_starter_has_required_files(starter: str) -> None:
    base = _STARTERS_DIR / starter
    for required in ("main.py", "tools.py", "config.py", "requirements.txt", "README.md"):
        assert (base / required).exists(), f"{starter}/{required} missing"


def test_enterprise_has_extra_files() -> None:
    base = _STARTERS_DIR / "enterprise"
    for required in (
        "security_policy.py",
        "llm_routing.py",
        "docker-compose.yml",
        ".env.example",
        "Dockerfile",
    ):
        assert (base / required).exists(), f"enterprise/{required} missing"


# ---------------------------------------------------------------------------
# config.py — swap AnthropicProvider for a mock and build the agent
# ---------------------------------------------------------------------------


def _make_mock_planner(*_args, **_kwargs) -> MockLLMProvider:
    return MockLLMProvider()


@pytest.mark.parametrize(
    "starter",
    ["chatbot", "filemanager", "devops", "office", "data", "browser"],
)
def test_config_build_agent_with_mock_llm(starter: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Patch the LLM providers BEFORE importing config (which instantiates them).
    import yagura.llm

    monkeypatch.setattr(yagura.llm, "AnthropicProvider", _make_mock_planner, raising=True)
    monkeypatch.setattr(yagura.llm, "OllamaProvider", _make_mock_planner, raising=True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    # Point file loggers into a temp dir so we don't pollute the repo.
    monkeypatch.chdir(tmp_path)

    config_mod = _load(starter, "config")
    agent = config_mod.build_agent()
    # Agent should have the starter's declared tools.
    tool_names = [t.name for t in agent.tool_registry.list_all()]
    assert len(tool_names) > 0


# ---------------------------------------------------------------------------
# End-to-end: chatbot can run a plan against mock tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chatbot_runs_an_end_to_end_plan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Smoke-test: chatbot's build_agent() produces an Agent that can execute a canned plan."""

    mock_planner = MockLLMProvider(
        responses=[
            plan_tool_response(
                [
                    {
                        "step_number": 1,
                        "tool_name": "directory_list",
                        "parameters": {"path": str(tmp_path)},
                        "description": f"List files in {tmp_path}",
                    }
                ]
            )
        ]
    )

    def _fake_provider(*_args, **_kwargs):
        return mock_planner

    import yagura.llm

    monkeypatch.setattr(yagura.llm, "AnthropicProvider", _fake_provider, raising=True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.chdir(tmp_path)

    config_mod = _load("chatbot", "config")
    agent = config_mod.build_agent()

    # development preset: READ + MODIFY auto-execute, so this runs without prompting.
    # However, default_reliability on common tools is AUTHORITATIVE, so no REFERENCE
    # confirmation is triggered either.
    response = await agent.run("list files here")
    assert response.plan.state.value == "completed"
    assert response.plan.steps[0].result is not None
    assert response.plan.steps[0].result.success is True


# ---------------------------------------------------------------------------
# Enterprise config requires a bunch of env vars — just check it imports cleanly.
# ---------------------------------------------------------------------------


def test_enterprise_config_imports_without_executing_build_agent() -> None:
    """The enterprise config imports many packages at module load time; make sure
    that the module is syntactically valid and all imports succeed."""
    # Just import it — don't call build_agent(), which requires real env vars.
    path = _STARTERS_DIR / "enterprise" / "config.py"
    spec = importlib.util.spec_from_file_location("enterprise_config", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Add the starter and _shared dirs so `from tools import ...` etc resolve.
    sys.path.insert(0, str(path.parent))
    sys.path.insert(0, str(_SHARED_DIR))
    # Evict cached modules from other starters.
    for key in ("tools", "config", "security_policy", "llm_routing"):
        sys.modules.pop(key, None)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
        sys.path.remove(str(_SHARED_DIR))
    assert hasattr(module, "build_agent")
