"""Process listing and termination."""

from __future__ import annotations

import os
import signal
import sys
from typing import Any

from yagura import DangerLevel, Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


def _process_list(filter: str | None = None) -> ToolResult:
    """List running processes. Tries psutil first, falls back to platform tools."""
    try:
        import psutil  # type: ignore

        procs: list[dict[str, Any]] = []
        for p in psutil.process_iter(["pid", "name", "username", "cmdline"]):
            info = p.info
            if filter and filter.lower() not in (info.get("name") or "").lower():
                continue
            procs.append(
                {
                    "pid": info["pid"],
                    "name": info.get("name"),
                    "user": info.get("username"),
                    "cmdline": " ".join(info.get("cmdline") or []),
                }
            )
        return ToolResult(success=True, data={"processes": procs, "count": len(procs)})
    except ImportError:
        pass

    # Platform fallback.
    if sys.platform == "win32":
        import subprocess  # noqa: PLC0415 — platform fallback only.

        out = subprocess.check_output(["tasklist", "/FO", "CSV", "/NH"], text=True, errors="replace")
        procs = []
        for line in out.splitlines():
            cells = [c.strip().strip('"') for c in line.split('","')]
            if len(cells) < 2:
                continue
            name, pid = cells[0].lstrip('"'), cells[1]
            if filter and filter.lower() not in name.lower():
                continue
            try:
                procs.append({"pid": int(pid), "name": name})
            except ValueError:
                continue
        return ToolResult(success=True, data={"processes": procs, "count": len(procs)})

    import subprocess  # noqa: PLC0415

    out = subprocess.check_output(["ps", "-eo", "pid,user,comm"], text=True, errors="replace")
    procs = []
    for line in out.splitlines()[1:]:
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        pid, user, comm = parts
        if filter and filter.lower() not in comm.lower():
            continue
        try:
            procs.append({"pid": int(pid), "user": user, "name": comm})
        except ValueError:
            continue
    return ToolResult(success=True, data={"processes": procs, "count": len(procs)})


def _process_kill(pid: int, signal_name: str = "TERM") -> ToolResult:
    try:
        sig = getattr(signal, f"SIG{signal_name}", signal.SIGTERM)
        os.kill(pid, sig)
    except ProcessLookupError:
        return ToolResult(success=False, error=f"No such process: {pid}")
    except PermissionError as exc:
        return ToolResult(success=False, error=f"Permission denied: {exc}")
    return ToolResult(success=True, data={"pid": pid, "signal": signal_name})


process_list = Tool(
    name="process_list",
    description="List running processes (pid, name, user).",
    parameters={
        "type": "object",
        "properties": {"filter": {"type": "string", "description": "Substring to match process names."}},
        "required": [],
    },
    handler=_process_list,
    danger_level=DangerLevel.READ,
    default_reliability=ReliabilityLevel.AUTHORITATIVE,
    tags=["common", "process"],
)

process_kill = Tool(
    name="process_kill",
    description="Terminate a process by PID.",
    parameters={
        "type": "object",
        "properties": {
            "pid": {"type": "integer"},
            "signal_name": {"type": "string", "default": "TERM"},
        },
        "required": ["pid"],
    },
    handler=_process_kill,
    danger_level=DangerLevel.DESTRUCTIVE,
    tags=["common", "process"],
)


tools: list[Tool] = [process_list, process_kill]
