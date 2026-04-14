"""yagura-tools-docker — Docker container/image operations."""

from __future__ import annotations

from typing import Any

from yagura import DangerLevel, Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


def _lazy_docker():
    try:
        import docker  # type: ignore
    except ImportError as exc:
        raise ImportError("yagura-tools-docker requires 'docker'") from exc
    return docker


def _client():
    return _lazy_docker().from_env()


def _container_to_dict(c: Any) -> dict[str, Any]:
    return {
        "id": c.id[:12],
        "name": c.name,
        "image": c.image.tags[0] if c.image.tags else c.image.id[:12],
        "status": c.status,
        "ports": c.ports,
    }


def _docker_container_list(all: bool = False) -> ToolResult:
    client = _client()
    containers = [_container_to_dict(c) for c in client.containers.list(all=all)]
    return ToolResult(success=True, data={"containers": containers, "count": len(containers)})


def _docker_container_run(
    image: str,
    command: str | None = None,
    ports: dict[str, int] | None = None,
    env: dict[str, str] | None = None,
    detach: bool = True,
) -> ToolResult:
    client = _client()
    container = client.containers.run(
        image=image,
        command=command,
        ports=ports,
        environment=env,
        detach=detach,
    )
    return ToolResult(success=True, data=_container_to_dict(container))


def _docker_container_stop(container_id: str, timeout: int = 10) -> ToolResult:
    client = _client()
    container = client.containers.get(container_id)
    container.stop(timeout=timeout)
    return ToolResult(success=True, data={"id": container_id, "stopped": True})


def _docker_container_remove(container_id: str, force: bool = False) -> ToolResult:
    client = _client()
    container = client.containers.get(container_id)
    container.remove(force=force)
    return ToolResult(success=True, data={"id": container_id, "removed": True})


def _docker_container_logs(container_id: str, tail: int = 100) -> ToolResult:
    client = _client()
    container = client.containers.get(container_id)
    logs = container.logs(tail=tail).decode("utf-8", errors="replace")
    return ToolResult(
        success=True,
        data={"id": container_id, "logs": logs},
        reliability=ReliabilityLevel.AUTHORITATIVE,
    )


def _docker_container_exec(container_id: str, command: str) -> ToolResult:
    client = _client()
    container = client.containers.get(container_id)
    result = container.exec_run(command)
    return ToolResult(
        success=result.exit_code == 0,
        data={
            "exit_code": result.exit_code,
            "output": result.output.decode("utf-8", errors="replace"),
        },
    )


def _docker_image_build(path: str, tag: str) -> ToolResult:
    client = _client()
    image, _logs = client.images.build(path=path, tag=tag)
    return ToolResult(
        success=True,
        data={"id": image.id[:12], "tags": image.tags},
    )


def _docker_image_pull(image: str, tag: str = "latest") -> ToolResult:
    client = _client()
    pulled = client.images.pull(image, tag=tag)
    tags = pulled.tags if hasattr(pulled, "tags") else []
    return ToolResult(success=True, data={"image": image, "tag": tag, "tags": tags})


def _docker_image_list() -> ToolResult:
    client = _client()
    images = [
        {"id": img.id[:12], "tags": img.tags, "size": img.attrs.get("Size")}
        for img in client.images.list()
    ]
    return ToolResult(success=True, data={"images": images, "count": len(images)})


def _docker_image_remove(image: str, force: bool = False) -> ToolResult:
    client = _client()
    client.images.remove(image=image, force=force)
    return ToolResult(success=True, data={"image": image, "removed": True})


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


docker_container_list = Tool(
    name="docker_container_list",
    description="List Docker containers.",
    parameters={
        "type": "object",
        "properties": {"all": {"type": "boolean", "default": False}},
        "required": [],
    },
    handler=_docker_container_list,
    danger_level=DangerLevel.READ,
    default_reliability=ReliabilityLevel.AUTHORITATIVE,
    tags=["docker"],
)

docker_container_run = Tool(
    name="docker_container_run",
    description="Run a new container.",
    parameters={
        "type": "object",
        "properties": {
            "image": {"type": "string"},
            "command": {"type": "string"},
            "ports": {"type": "object"},
            "env": {"type": "object"},
            "detach": {"type": "boolean", "default": True},
        },
        "required": ["image"],
    },
    handler=_docker_container_run,
    danger_level=DangerLevel.MODIFY,
    tags=["docker"],
)

docker_container_stop = Tool(
    name="docker_container_stop",
    description="Stop a running container.",
    parameters={
        "type": "object",
        "properties": {"container_id": {"type": "string"}, "timeout": {"type": "integer", "default": 10}},
        "required": ["container_id"],
    },
    handler=_docker_container_stop,
    danger_level=DangerLevel.MODIFY,
    tags=["docker"],
)

docker_container_remove = Tool(
    name="docker_container_remove",
    description="Remove a container.",
    parameters={
        "type": "object",
        "properties": {"container_id": {"type": "string"}, "force": {"type": "boolean", "default": False}},
        "required": ["container_id"],
    },
    handler=_docker_container_remove,
    danger_level=DangerLevel.DESTRUCTIVE,
    tags=["docker"],
)

docker_container_logs = Tool(
    name="docker_container_logs",
    description="Get container logs.",
    parameters={
        "type": "object",
        "properties": {"container_id": {"type": "string"}, "tail": {"type": "integer", "default": 100}},
        "required": ["container_id"],
    },
    handler=_docker_container_logs,
    danger_level=DangerLevel.READ,
    default_reliability=ReliabilityLevel.AUTHORITATIVE,
    tags=["docker"],
)

docker_container_exec = Tool(
    name="docker_container_exec",
    description="Execute a command inside a container.",
    parameters={
        "type": "object",
        "properties": {"container_id": {"type": "string"}, "command": {"type": "string"}},
        "required": ["container_id", "command"],
    },
    handler=_docker_container_exec,
    requires_llm=True,
    tags=["docker"],
)

docker_image_build = Tool(
    name="docker_image_build",
    description="Build a Docker image from a Dockerfile.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}, "tag": {"type": "string"}},
        "required": ["path", "tag"],
    },
    handler=_docker_image_build,
    danger_level=DangerLevel.MODIFY,
    tags=["docker"],
)

docker_image_pull = Tool(
    name="docker_image_pull",
    description="Pull a Docker image.",
    parameters={
        "type": "object",
        "properties": {"image": {"type": "string"}, "tag": {"type": "string", "default": "latest"}},
        "required": ["image"],
    },
    handler=_docker_image_pull,
    danger_level=DangerLevel.MODIFY,
    tags=["docker"],
)

docker_image_list = Tool(
    name="docker_image_list",
    description="List local Docker images.",
    parameters={"type": "object", "properties": {}, "required": []},
    handler=_docker_image_list,
    danger_level=DangerLevel.READ,
    default_reliability=ReliabilityLevel.AUTHORITATIVE,
    tags=["docker"],
)

docker_image_remove = Tool(
    name="docker_image_remove",
    description="Remove a Docker image.",
    parameters={
        "type": "object",
        "properties": {"image": {"type": "string"}, "force": {"type": "boolean", "default": False}},
        "required": ["image"],
    },
    handler=_docker_image_remove,
    danger_level=DangerLevel.DESTRUCTIVE,
    tags=["docker"],
)


tools: list[Tool] = [
    docker_container_list,
    docker_container_run,
    docker_container_stop,
    docker_container_remove,
    docker_container_logs,
    docker_container_exec,
    docker_image_build,
    docker_image_pull,
    docker_image_list,
    docker_image_remove,
]

__all__ = ["tools"]
