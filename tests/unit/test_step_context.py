"""StepContext / $step_N reference resolution — P0."""

from __future__ import annotations

import pytest

from yagura.errors import StepReferenceError
from yagura.plan import StepContext
from yagura.tools.tool import ToolResult


def _context_with(step: int, data) -> StepContext:
    ctx = StepContext()
    ctx.record(step, ToolResult(success=True, data=data))
    return ctx


def test_resolve_direct_path() -> None:
    ctx = _context_with(1, {"files": ["/tmp/a.txt", "/tmp/b.txt"]})
    assert ctx.resolve_ref("$step_1.data.files[0]") == "/tmp/a.txt"
    assert ctx.resolve_ref("$step_1.data.files[1]") == "/tmp/b.txt"


def test_resolve_attribute_access_on_tool_result() -> None:
    ctx = _context_with(2, 42)
    assert ctx.resolve_ref("$step_2.data") == 42
    assert ctx.resolve_ref("$step_2.success") is True


def test_missing_path_raises() -> None:
    ctx = _context_with(1, {"files": []})
    with pytest.raises(StepReferenceError):
        ctx.resolve_ref("$step_1.data.missing")


def test_missing_step_raises() -> None:
    ctx = StepContext()
    with pytest.raises(StepReferenceError):
        ctx.resolve_ref("$step_1.data")


def test_malformed_ref_raises() -> None:
    ctx = _context_with(1, {})
    with pytest.raises(StepReferenceError):
        ctx.resolve_ref("not-a-ref")


def test_nested_dict_resolution() -> None:
    ctx = _context_with(1, {"users": {"alice": {"age": 30}}})
    assert ctx.resolve_ref("$step_1.data.users.alice.age") == 30


def test_record_overwrites_previous() -> None:
    ctx = StepContext()
    ctx.record(1, ToolResult(success=True, data="v1"))
    ctx.record(1, ToolResult(success=True, data="v2"))
    assert ctx.get(1).data == "v2"
