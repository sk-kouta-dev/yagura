"""Agent — the top-level entry point that ties everything together."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from yagura.confirmation.handler import AutoApproveHandler
from yagura.errors import PlanError
from yagura.plan import (
    Plan,
    PlanConfirmation,
    PlanExecutor,
    Planner,
    PlanState,
    StepContext,
    StepStatus,
    make_plan_summary,
)
from yagura.rules.engine import RuleEngine
from yagura.rules.rule import Rule
from yagura.safety.assessor import DangerAssessor
from yagura.session.manager import ConversationTurn, Session, SessionManager
from yagura.tools.executor import ToolExecutor
from yagura.tools.registry import ToolRegistry
from yagura.tools.tool import Tool


@dataclass
class AgentResponse:
    """Return value from `Agent.run`."""

    session: Session
    plan: Plan
    needs_confirmation: bool = False
    message: str | None = None
    summary: Any = None
    extras: dict[str, Any] = field(default_factory=dict)


class Agent:
    """Top-level Yagura agent.

    Typical usage:

        agent = Agent(Config(planner_llm=AnthropicProvider(model=...)))
        agent.register_tool(my_tool)
        response = await agent.run("do something")
        if response.needs_confirmation:
            response = await agent.confirm(response.session.id, PlanConfirmation(approved=True))
    """

    def __init__(self, config: Config) -> None:  # type: ignore[name-defined]  # noqa: F821 — forward ref below
        from yagura.config import Config  # Local import avoids circular dependency.

        if not isinstance(config, Config):
            raise TypeError("Agent(config=) must be a yagura.Config instance")

        self.config = config
        self.tool_registry = ToolRegistry()
        self.session_manager = SessionManager(
            state_store=config.state_store,
            max_concurrent_sessions=config.max_concurrent_sessions,
        )
        self.audit_logger = config.logger
        self.auth_provider = config.auth_provider
        self.planner = Planner(config.planner_llm)  # type: ignore[arg-type]
        self.tool_executor = ToolExecutor(
            remote_executor=config.remote_executor,
            client_executor=config.client_executor,
        )
        self.danger_assessor = DangerAssessor(
            rules=config.danger_rules,
            executor_llm=config.effective_executor_llm,
            fallback_llm=config.fallback_llm,
            policy_provider=config.security_policy_provider,
            auto_execute_threshold=config.auto_execute_threshold,
            confidence_threshold=config.assessment_confidence_threshold,
        )
        self.confirmation_handler = config.confirmation_handler
        self.rule_engine = RuleEngine(self)
        for rule in config.rules:
            self.rule_engine.add_rule(rule)

        # Per-session pause events. Setting an event makes the PlanExecutor
        # transition its plan to PAUSED between steps and return control.
        self._pause_events: dict[str, asyncio.Event] = {}

        # Number of recent ConversationTurns to include in the Planner
        # system prompt. Bounded to keep token usage predictable.
        self.history_max_turns: int = 6

    # --- Tool registration -----------------------------------------------

    def register_tool(self, tool: Tool) -> None:
        self.tool_registry.register(tool)

    def register_tools(self, tools: list[Tool]) -> None:
        for tool in tools:
            self.register_tool(tool)

    def load_tools_from_schema(self, source: Any) -> None:
        self.tool_registry.load_from_schema(source)

    # --- Main entry point ------------------------------------------------

    async def run(
        self,
        user_input: str,
        session_id: str | None = None,
        user_id: str = "default",
    ) -> AgentResponse:
        """Generate a plan from user_input and either auto-execute or return for confirmation."""
        from yagura.telemetry import span

        with span("yagura.agent.run", user_id=user_id, prompt_len=len(user_input)):
            return await self._run_impl(user_input, session_id, user_id)

    async def _run_impl(
        self,
        user_input: str,
        session_id: str | None,
        user_id: str,
    ) -> AgentResponse:
        session = await self.session_manager.get_or_create(session_id, user_id)

        # Construct a system prompt that includes a compact summary of prior
        # turns so the Planner can interpret "the file from earlier" etc.
        planner_system = self._planner_system_prompt(session)

        plan = await self.planner.generate(
            user_input=user_input,
            tool_schemas=self.tool_registry.get_schemas(),
            system=planner_system,
        )

        # Assess every step up front so auto-execute can decide.
        await self._prefill_danger_levels(plan)

        session.plan = plan
        await self.session_manager.save(session)

        summary = make_plan_summary(plan, self.tool_registry)

        if self._can_auto_execute(plan):
            # Skip user confirmation; execute immediately.
            executed = await self._execute(session, plan)
            self._append_turn(session, user_input, executed)
            await self.session_manager.save(session)
            return AgentResponse(
                session=session,
                plan=executed,
                needs_confirmation=False,
                summary=summary,
            )

        # Plans with dangerous steps return to the user for confirmation.
        # The pending user_input is stashed so `confirm()` can record the turn.
        session.context["pending_user_input"] = user_input
        await self.session_manager.save(session)
        return AgentResponse(
            session=session,
            plan=plan,
            needs_confirmation=True,
            summary=summary,
            message="Plan requires user confirmation.",
        )

    async def run_stream(
        self,
        user_input: str,
        session_id: str | None = None,
        user_id: str = "default",
    ):
        """Streaming variant of `run`: yields StreamEvent objects as the plan progresses.

        Events (see yagura.streaming):
          - PlanGenerated
          - PlanNeedsConfirmation (caller should call agent.confirm_stream(...) after)
          - StepStarted / StepCompleted / StepFailed (per step)
          - PlanCompleted / PlanFailed / PlanPaused (terminal)

        Usage::

            async for event in agent.run_stream("do something"):
                await websocket.send_json(event_to_dict(event))
        """
        from yagura.streaming import PlanGenerated, PlanNeedsConfirmation

        session = await self.session_manager.get_or_create(session_id, user_id)
        planner_system = self._planner_system_prompt(session)

        plan = await self.planner.generate(
            user_input=user_input,
            tool_schemas=self.tool_registry.get_schemas(),
            system=planner_system,
        )
        await self._prefill_danger_levels(plan)
        session.plan = plan
        await self.session_manager.save(session)

        yield PlanGenerated(session_id=session.id, plan=plan)

        if not self._can_auto_execute(plan):
            session.context["pending_user_input"] = user_input
            await self.session_manager.save(session)
            yield PlanNeedsConfirmation(
                session_id=session.id,
                plan=plan,
                reason="Plan contains steps above auto_execute_threshold.",
            )
            return

        executor = self._make_executor(session)
        context = _build_context_from_plan(plan)
        async for event in executor.execute_stream(plan, context):
            yield event
        session.plan = plan
        self._append_turn(session, user_input, plan)
        await self.session_manager.save(session)

    async def confirm_stream(
        self,
        session_id: str,
        confirmation: PlanConfirmation,
    ):
        """Streaming variant of `confirm`."""
        from yagura.streaming import PlanCancelled

        session = await self.session_manager.load(session_id)
        if session.plan is None:
            raise PlanError(f"Session {session_id} has no plan pending confirmation")
        plan = session.plan
        if plan.state is not PlanState.DRAFT:
            raise PlanError(f"Plan {plan.id} is in state {plan.state.value}, cannot confirm")
        pending_input = session.context.pop("pending_user_input", "") or ""

        if not confirmation.approved:
            plan.transition_to(PlanState.CANCELLED)
            self._append_turn(session, pending_input, plan)
            await self.session_manager.save(session)
            yield PlanCancelled(session_id=session.id, plan=plan)
            return

        plan.scope = confirmation.scope
        plan.transition_to(PlanState.CONFIRMED)
        executor = self._make_executor(session)
        context = _build_context_from_plan(plan)
        async for event in executor.execute_stream(plan, context):
            yield event
        session.plan = plan
        self._append_turn(session, pending_input, plan)
        await self.session_manager.save(session)

    async def confirm(
        self,
        session_id: str,
        confirmation: PlanConfirmation,
    ) -> AgentResponse:
        """Apply a PlanConfirmation to a pending plan and execute if approved."""
        session = await self.session_manager.load(session_id)
        if session.plan is None:
            raise PlanError(f"Session {session_id} has no plan pending confirmation")
        plan = session.plan
        if plan.state is not PlanState.DRAFT:
            raise PlanError(f"Plan {plan.id} is in state {plan.state.value}, cannot confirm")

        pending_input = session.context.pop("pending_user_input", "") or ""

        if not confirmation.approved:
            plan.transition_to(PlanState.CANCELLED)
            self._append_turn(session, pending_input, plan)
            await self.session_manager.save(session)
            return AgentResponse(
                session=session,
                plan=plan,
                needs_confirmation=False,
                message="User cancelled plan.",
            )

        plan.scope = confirmation.scope
        plan.transition_to(PlanState.CONFIRMED)
        executed = await self._execute(session, plan)
        self._append_turn(session, pending_input, executed)
        await self.session_manager.save(session)
        return AgentResponse(
            session=session,
            plan=executed,
            needs_confirmation=False,
            summary=make_plan_summary(executed, self.tool_registry),
        )

    # --- Rule execution (called by RuleEngine callback) ------------------

    async def run_as_rule(self, rule: Rule, trigger_payload: dict[str, Any]) -> Plan:
        """Execute a rule's plan template as pre-approved automation."""
        session = await self.session_manager.create(user_id=f"rule:{rule.id}")

        user_input = rule.plan_template
        if trigger_payload:
            user_input = f"{rule.plan_template}\n\nTrigger payload: {trigger_payload!r}"
        plan = await self.planner.generate(
            user_input=user_input,
            tool_schemas=self.tool_registry.get_schemas(),
        )
        await self._prefill_danger_levels(plan)
        session.plan = plan
        await self.session_manager.save(session)

        # Rules are pre-approved; use AutoApproveHandler for the plan level,
        # but per-step DangerAssessor still applies.
        executor = self._make_executor(
            session,
            confirmation_handler_override=AutoApproveHandler(),
        )
        plan.transition_to(PlanState.CONFIRMED)
        executed = await executor.execute(plan)
        await self.session_manager.save(session)
        return executed

    # --- Rule engine lifecycle -------------------------------------------

    async def start(self) -> None:
        """Start the rule engine (begins running all enabled triggers)."""
        await self.rule_engine.start()

    async def stop(self) -> None:
        """Stop the rule engine."""
        await self.rule_engine.stop()

    # --- Internals -------------------------------------------------------

    def _make_executor(
        self,
        session: Session,
        confirmation_handler_override: Any = None,
    ) -> PlanExecutor:
        return PlanExecutor(
            tool_registry=self.tool_registry,
            tool_executor=self.tool_executor,
            danger_assessor=self.danger_assessor,
            confirmation_handler=confirmation_handler_override or self.confirmation_handler,
            executor_llm=self.config.effective_executor_llm,
            audit_logger=self.audit_logger,
            session_id=session.id,
            user_id=session.user_id,
            pause_event=self._pause_events.get(session.id),
        )

    async def _execute(self, session: Session, plan: Plan) -> Plan:
        context = _build_context_from_plan(plan)
        executor = self._make_executor(session)
        await executor.execute(plan, context)
        session.plan = plan
        await self.session_manager.save(session)
        return plan

    # --- Pause / resume --------------------------------------------------

    async def pause(self, session_id: str) -> None:
        """Signal the currently-executing plan in this session to pause.

        The PlanExecutor checks the pause flag between steps; on the next
        gap it transitions the plan to PAUSED and stops. Already-completed
        step results are preserved on the Plan and persisted to the
        StateStore.
        """
        event = self._pause_events.setdefault(session_id, asyncio.Event())
        event.set()

    async def resume(self, session_id: str) -> AgentResponse:
        """Continue a PAUSED plan from the next pending step."""
        session = await self.session_manager.load(session_id)
        if session.plan is None:
            raise PlanError(f"Session {session_id} has no plan to resume")
        if session.plan.state is not PlanState.PAUSED:
            raise PlanError(f"Plan {session.plan.id} is in state {session.plan.state.value}, expected PAUSED to resume")
        # Clear any pending pause signal.
        event = self._pause_events.get(session_id)
        if event is not None:
            event.clear()

        executed = await self._execute(session, session.plan)
        return AgentResponse(
            session=session,
            plan=executed,
            needs_confirmation=False,
            summary=make_plan_summary(executed, self.tool_registry),
        )

    async def _prefill_danger_levels(self, plan: Plan) -> None:
        """Run layer-1 rule classification on every step so summaries are accurate.

        Full LLM-based assessment is deferred to execution time (when
        parameters may have been resolved from prior steps).
        """
        for step in plan.steps:
            if not self.tool_registry.has(step.tool_name):
                continue
            tool = self.tool_registry.get(step.tool_name)
            if tool.danger_level is not None:
                step.danger_level = tool.danger_level
                continue
            rule_level = self.config.danger_rules.classify(tool.name)
            if rule_level is not None:
                step.danger_level = rule_level

    def _planner_system_prompt(self, session: Session) -> str | None:
        """Build the Planner system prompt with conversation history prepended."""
        recent = session.history[-self.history_max_turns :] if session.history else []
        if not recent:
            return None  # Fall back to LLMProvider.generate_plan default.
        return _format_history(recent) + "\n\n" + _DEFAULT_PLANNER_SYSTEM

    def _append_turn(self, session: Session, user_input: str, plan: Plan) -> None:
        """Record a completed turn so the next Planner call has context."""
        if not user_input:
            return
        session.history.append(
            ConversationTurn(
                user_input=user_input,
                plan_id=plan.id,
                plan_state=plan.state.value,
                step_summaries=[_summarize_step(s) for s in plan.steps],
            )
        )
        # Bound history growth on the Session itself (Planner trims again at
        # prompt-build time, but we also cap storage to avoid unbounded JSONB).
        max_kept = max(self.history_max_turns * 4, 32)
        if len(session.history) > max_kept:
            session.history = session.history[-max_kept:]

    def _can_auto_execute(self, plan: Plan) -> bool:
        threshold = self.config.auto_execute_threshold
        if threshold is None:
            return False
        for step in plan.steps:
            if step.danger_level is None:
                # Unknown → conservative: require confirmation.
                return False
            if step.danger_level > threshold:
                return False
        return True


_DEFAULT_PLANNER_SYSTEM = (
    "You are the Planner for an AI agent. Given the user's request and the "
    "available tools, produce a step-by-step execution plan by calling the "
    "`create_plan` tool. Each step must reference exactly one registered tool. "
    "Use $step_N.field references to pass data between steps. Do not invent tools."
)


def _format_history(turns: list[ConversationTurn]) -> str:
    """Render recent conversation turns as a compact plain-text block."""
    lines = ["Prior conversation turns (most recent last):"]
    for i, turn in enumerate(turns, start=1):
        lines.append(f"  [{i}] user: {turn.user_input}")
        lines.append(f"      plan {turn.plan_state}")
        for summary in turn.step_summaries[:6]:
            lines.append(f"        - {summary}")
    return "\n".join(lines)


def _summarize_step(step) -> str:  # type: ignore[no-untyped-def]
    """One-line summary of a PlanStep for conversation history."""
    status = step.status.value
    pieces = [f"step {step.step_number} [{status}]"]
    if step.tool_name:
        pieces.append(f"tool={step.tool_name}")
    if step.description:
        pieces.append(step.description)
    if step.error:
        pieces.append(f"error={step.error}")
    return " · ".join(pieces)


def _build_context_from_plan(plan: Plan) -> StepContext:
    """Reconstruct a StepContext from a Plan's already-completed step results.

    Used on initial execution (no prior results → empty context) and on
    resume after a pause (populated from the Plan's preserved step.result
    values, so downstream $step_N references still resolve).
    """
    ctx = StepContext()
    for step in plan.steps:
        if step.status is StepStatus.COMPLETED and step.result is not None:
            ctx.record(step.step_number, step.result)
    return ctx
