"""yagura-tools-openapi — auto-generate Yagura tools from OpenAPI specs.

Typical usage:

    from yagura_tools.openapi import OpenAPIToolGenerator
    gen = OpenAPIToolGenerator()
    tools = gen.from_url("https://petstore.swagger.io/v2/swagger.json", auth_header="Bearer xxx")
    agent.register_tools(tools)

Each endpoint becomes a Tool named `{spec_name}_{operation_id}`.
DangerLevel is inferred from HTTP method:
  - GET / HEAD / OPTIONS → READ
  - POST / PUT / PATCH → MODIFY
  - DELETE → DESTRUCTIVE
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from yagura import DangerLevel, Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


_METHOD_DANGER = {
    "GET": DangerLevel.READ,
    "HEAD": DangerLevel.READ,
    "OPTIONS": DangerLevel.READ,
    "POST": DangerLevel.MODIFY,
    "PUT": DangerLevel.MODIFY,
    "PATCH": DangerLevel.MODIFY,
    "DELETE": DangerLevel.DESTRUCTIVE,
}


class OpenAPIToolGenerator:
    """Generates Tool objects from an OpenAPI 3.x (or Swagger 2.0) spec."""

    def __init__(self) -> None:
        self._specs: dict[str, dict[str, Any]] = {}

    # --- Loading ----------------------------------------------------------

    def from_url(self, url: str, auth_header: str | None = None, spec_name: str | None = None) -> list[Tool]:
        import httpx

        response = httpx.get(url, timeout=30)
        response.raise_for_status()
        return self._from_content(response.content, base_url=url, auth_header=auth_header, spec_name=spec_name)

    def from_file(self, path: str, base_url: str | None = None, auth_header: str | None = None, spec_name: str | None = None) -> list[Tool]:
        with open(path, "rb") as f:
            return self._from_content(f.read(), base_url=base_url, auth_header=auth_header, spec_name=spec_name)

    def _from_content(
        self,
        content: bytes | str,
        base_url: str | None = None,
        auth_header: str | None = None,
        spec_name: str | None = None,
    ) -> list[Tool]:
        spec = _parse_spec(content)
        spec_id = spec_name or _sanitize(spec.get("info", {}).get("title", f"api_{uuid4().hex[:6]}"))
        server_url = base_url or _first_server(spec)
        self._specs[spec_id] = {"spec": spec, "server": server_url, "auth": auth_header}

        tools: list[Tool] = []
        paths = spec.get("paths") or {}
        for path, methods in paths.items():
            for method, operation in methods.items():
                if method.upper() not in _METHOD_DANGER:
                    continue
                tools.append(self._build_tool(spec_id, path, method.upper(), operation))
        return tools

    # --- Tool factory -----------------------------------------------------

    def _build_tool(self, spec_id: str, path: str, method: str, operation: dict[str, Any]) -> Tool:
        operation_id = operation.get("operationId") or _sanitize(f"{method.lower()}_{path}")
        name = f"{spec_id}_{operation_id}"
        description = operation.get("summary") or operation.get("description") or f"{method} {path}"
        parameters = self._build_parameters_schema(operation)

        spec_data = self._specs[spec_id]
        server_url = spec_data["server"]
        auth_header = spec_data["auth"]

        async def handler(**kwargs: Any) -> ToolResult:
            import httpx

            url, path_params, query_params, headers, body = self._resolve_call(path, operation, kwargs)
            if auth_header:
                headers.setdefault("Authorization", auth_header)
            target = f"{server_url.rstrip('/')}{url}"
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.request(
                    method=method,
                    url=target,
                    params=query_params,
                    headers=headers,
                    json=body if body is not None else None,
                )
            try:
                payload: Any = response.json()
            except ValueError:
                payload = response.text
            return ToolResult(
                success=response.is_success,
                data={"status": response.status_code, "body": payload, "url": target},
                error=None if response.is_success else f"HTTP {response.status_code}",
            )

        return Tool(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            danger_level=_METHOD_DANGER[method],
            default_reliability=ReliabilityLevel.AUTHORITATIVE if method == "GET" else ReliabilityLevel.VERIFIED,
            tags=["openapi", spec_id],
        )

    def _build_parameters_schema(self, operation: dict[str, Any]) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param in operation.get("parameters", []) or []:
            name = param["name"]
            schema = param.get("schema") or {"type": param.get("type", "string")}
            properties[name] = {**schema, "description": param.get("description", "")}
            if param.get("required"):
                required.append(name)
        body = operation.get("requestBody")
        if body:
            content = body.get("content") or {}
            for media_type, media in content.items():
                if media_type.startswith("application/json"):
                    properties["body"] = media.get("schema") or {"type": "object"}
                    if body.get("required"):
                        required.append("body")
                    break
        return {"type": "object", "properties": properties, "required": required}

    def _resolve_call(self, path: str, operation: dict[str, Any], kwargs: dict[str, Any]):
        path_params: dict[str, str] = {}
        query_params: dict[str, Any] = {}
        headers: dict[str, str] = {}
        body: Any = kwargs.get("body")

        for param in operation.get("parameters", []) or []:
            name = param["name"]
            if name not in kwargs:
                continue
            loc = param.get("in")
            if loc == "path":
                path_params[name] = str(kwargs[name])
            elif loc == "query":
                query_params[name] = kwargs[name]
            elif loc == "header":
                headers[name] = str(kwargs[name])

        # Substitute path parameters.
        resolved_path = path
        for k, v in path_params.items():
            resolved_path = resolved_path.replace("{" + k + "}", v)
        return resolved_path, path_params, query_params, headers, body


# ---------------------------------------------------------------------------
# Built-in wrapper tools (for agent-side workflow)
# ---------------------------------------------------------------------------


_shared_generator = OpenAPIToolGenerator()
_dynamic_tools: dict[str, list[Tool]] = {}


def _openapi_load(source: str, auth_header: str | None = None, spec_name: str | None = None) -> ToolResult:
    """Load a spec (URL or file path). Returns a spec_id and list of generated tools."""
    if source.startswith(("http://", "https://")):
        tools = _shared_generator.from_url(source, auth_header=auth_header, spec_name=spec_name)
    else:
        tools = _shared_generator.from_file(source, auth_header=auth_header, spec_name=spec_name)
    spec_id = tools[0].tags[1] if tools and len(tools[0].tags) >= 2 else spec_name or str(uuid4())[:8]
    _dynamic_tools[spec_id] = tools
    return ToolResult(
        success=True,
        data={"spec_id": spec_id, "tools": [{"name": t.name, "danger": t.danger_level.name} for t in tools]},
    )


def _openapi_list_endpoints(spec_id: str) -> ToolResult:
    if spec_id not in _dynamic_tools:
        return ToolResult(success=False, error=f"spec_id not loaded: {spec_id}")
    return ToolResult(
        success=True,
        data={"endpoints": [{"name": t.name, "description": t.description} for t in _dynamic_tools[spec_id]]},
    )


async def _openapi_call(spec_id: str, operation_id: str, params: dict[str, Any] | None = None) -> ToolResult:
    if spec_id not in _dynamic_tools:
        return ToolResult(success=False, error=f"spec_id not loaded: {spec_id}")
    target = f"{spec_id}_{operation_id}"
    tool = next((t for t in _dynamic_tools[spec_id] if t.name == target), None)
    if tool is None:
        return ToolResult(success=False, error=f"operation not found: {operation_id}")
    return await tool.handler(**(params or {}))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_spec(content: bytes | str) -> dict[str, Any]:
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ImportError("YAML OpenAPI specs require 'pyyaml'") from exc
        return yaml.safe_load(text)


def _first_server(spec: dict[str, Any]) -> str:
    servers = spec.get("servers") or []
    if servers:
        return servers[0].get("url", "")
    # Swagger 2.0 fallback.
    host = spec.get("host", "")
    schemes = spec.get("schemes") or ["https"]
    base_path = spec.get("basePath", "")
    if host:
        return f"{schemes[0]}://{host}{base_path}"
    return ""


def _sanitize(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name).lower().strip("_")


openapi_load = Tool(
    name="openapi_load",
    description="Load an OpenAPI spec from a URL or file path and register its endpoints as callable tools.",
    parameters={
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "auth_header": {"type": "string"},
            "spec_name": {"type": "string"},
        },
        "required": ["source"],
    },
    handler=_openapi_load,
    danger_level=DangerLevel.READ,
    tags=["openapi"],
)

openapi_list_endpoints = Tool(
    name="openapi_list_endpoints",
    description="List endpoints discovered from a previously loaded OpenAPI spec.",
    parameters={
        "type": "object",
        "properties": {"spec_id": {"type": "string"}},
        "required": ["spec_id"],
    },
    handler=_openapi_list_endpoints,
    danger_level=DangerLevel.READ,
    default_reliability=ReliabilityLevel.AUTHORITATIVE,
    tags=["openapi"],
)

openapi_call = Tool(
    name="openapi_call",
    description="Invoke a specific operation on a loaded OpenAPI spec. Layer 2 classifies based on HTTP method.",
    parameters={
        "type": "object",
        "properties": {
            "spec_id": {"type": "string"},
            "operation_id": {"type": "string"},
            "params": {"type": "object"},
        },
        "required": ["spec_id", "operation_id"],
    },
    handler=_openapi_call,
    requires_llm=True,
    tags=["openapi"],
)


tools: list[Tool] = [openapi_load, openapi_list_endpoints, openapi_call]

__all__ = ["OpenAPIToolGenerator", "tools"]
