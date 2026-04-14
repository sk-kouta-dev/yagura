"""Thin CLI loop shared by the starter templates.

Each starter imports `run_repl(agent)` instead of rewriting the loop.
This is not a published package — it's copy/pastable boilerplate so
every starter remains self-contained after download.
"""

from __future__ import annotations

import asyncio
import sys
import traceback

from yagura import Agent, PlanConfirmation


async def run_repl(agent: Agent, welcome: str = "") -> None:
    """Minimal REPL: prompt → agent.run → handle confirmation → print result."""
    if welcome:
        print(welcome)
        print("Type 'quit' or 'exit' to leave.\n")
    session_id: str | None = None
    while True:
        try:
            user_input = await _aread_stdin("You: ")
        except EOFError:
            return
        user_input = user_input.strip()
        if not user_input:
            continue
        if user_input.lower() in {"quit", "exit", ":q"}:
            return

        try:
            response = await agent.run(user_input, session_id=session_id)
        except Exception:  # noqa: BLE001 — keep REPL alive on per-turn errors.
            print("! error while running the plan:", file=sys.stderr)
            traceback.print_exc()
            continue

        session_id = response.session.id

        if response.needs_confirmation:
            _render_plan_summary(response)
            approved = await _aread_stdin("Approve plan? [y/N] > ")
            if approved.strip().lower() not in {"y", "yes"}:
                print("(cancelled)\n")
                continue
            response = await agent.confirm(
                session_id=session_id,
                confirmation=PlanConfirmation(approved=True),
            )

        _render_result(response)


async def _aread_stdin(prompt: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: input(prompt))


def _render_plan_summary(response) -> None:  # type: ignore[no-untyped-def]
    print()
    print("Proposed plan:")
    for step in response.plan.steps:
        marker = f"[{step.danger_level.name}]" if step.danger_level else "[?]"
        print(f"  {step.step_number:>2}. {marker} {step.description}")
    print()


def _render_result(response) -> None:  # type: ignore[no-untyped-def]
    plan = response.plan
    print(f"\nPlan {plan.state.value}:")
    for step in plan.steps:
        status = step.status.value
        if step.result and step.result.success:
            preview = _preview(step.result.data)
            print(f"  {step.step_number:>2}. [{status}] {step.description} → {preview}")
        elif step.error:
            print(f"  {step.step_number:>2}. [{status}] {step.description} ! {step.error}")
        else:
            print(f"  {step.step_number:>2}. [{status}] {step.description}")
    print()


def _preview(data, limit: int = 160) -> str:
    import json

    try:
        text = json.dumps(data, ensure_ascii=False, default=str)
    except TypeError:
        text = repr(data)
    if len(text) > limit:
        return text[:limit] + f"... [truncated {len(text) - limit} chars]"
    return text
