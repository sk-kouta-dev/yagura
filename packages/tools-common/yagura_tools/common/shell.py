"""shell_execute — Dynamic Tool (Layer 2 assesses the command)."""

from __future__ import annotations

import asyncio
from typing import Any

from yagura import Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


async def _shell_execute(command: str, cwd: str | None = None, timeout: int = 60) -> ToolResult:
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return ToolResult(
            success=False,
            error=f"Command timed out after {timeout}s",
            data={"command": command, "cwd": cwd},
        )

    return ToolResult(
        success=proc.returncode == 0,
        data={
            "returncode": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        },
        error=stderr.decode("utf-8", errors="replace") if proc.returncode != 0 else None,
    )


shell_execute = Tool(
    name="shell_execute",
    description="Execute a shell command and return stdout/stderr/exit code.",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute."},
            "cwd": {"type": "string", "description": "Working directory.", "default": None},
            "timeout": {"type": "integer", "description": "Timeout in seconds.", "default": 60},
        },
        "required": ["command"],
    },
    handler=_shell_execute,
    # No danger_level: DangerAssessor Layer 2 inspects the command.
    requires_llm=True,
    default_reliability=ReliabilityLevel.REFERENCE,
    tags=["common", "shell"],
)


tools: list[Tool] = [shell_execute]
