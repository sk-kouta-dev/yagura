"""Optional OpenTelemetry integration.

If `opentelemetry-api` is installed, the framework emits spans for:
  - `yagura.plan.execute`      — whole plan
  - `yagura.plan.step`         — per step (with tool_name, danger_level attrs)
  - `yagura.llm.generate`      — each LLM call
  - `yagura.danger.assess`     — DangerAssessor classification

If OpenTelemetry is not installed, `_tracer` is a no-op and the instrumented
code paths work identically without any import-time cost.

Configuration: users wire up their own TracerProvider at startup, e.g.

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    trace.set_tracer_provider(TracerProvider())
    trace.get_tracer_provider().add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint="http://otel:4317"))
    )

After that, all Yagura spans flow to the configured exporter.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any


class _NoopSpan:
    def set_attribute(self, *_a, **_k) -> None:  # noqa: ANN002 ANN003
        return None

    def set_status(self, *_a, **_k) -> None:  # noqa: ANN002 ANN003
        return None

    def record_exception(self, *_a, **_k) -> None:  # noqa: ANN002 ANN003
        return None

    def __enter__(self):  # noqa: D401 ANN204 — context-manager protocol
        return self

    def __exit__(self, *_a) -> None:  # noqa: ANN002
        return None


class _NoopTracer:
    @contextmanager
    def start_as_current_span(self, _name: str, *args: Any, **kwargs: Any):
        yield _NoopSpan()


def _resolve_tracer():
    try:
        from opentelemetry import trace  # type: ignore

        return trace.get_tracer("yagura")
    except ImportError:
        return _NoopTracer()


_tracer = _resolve_tracer()


def tracer():
    """Return the active tracer. Always safe to call."""
    return _tracer


def span(name: str, **attributes: Any):
    """Context manager for a span with pre-populated attributes.

    Example::

        with span("yagura.plan.step", step_number=1, tool_name="shell_execute"):
            ...
    """

    @contextmanager
    def _ctx():
        with _tracer.start_as_current_span(name) as s:
            for k, v in attributes.items():
                if v is None:
                    continue
                try:
                    s.set_attribute(k, v)
                except Exception:  # noqa: BLE001
                    # OTEL attribute values must be str/int/float/bool — fall back to str.
                    s.set_attribute(k, str(v))
            try:
                yield s
            except Exception as exc:  # noqa: BLE001
                s.record_exception(exc)
                try:
                    from opentelemetry.trace import Status, StatusCode  # type: ignore

                    s.set_status(Status(StatusCode.ERROR, str(exc)))
                except ImportError:
                    pass
                raise

    return _ctx()
