"""yagura-tools-k8s — Kubernetes cluster management."""

from __future__ import annotations

import base64
from typing import Any

from yagura import DangerLevel, Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


_loaded = False


def _load_config() -> Any:
    global _loaded
    try:
        from kubernetes import client, config  # type: ignore
    except ImportError as exc:
        raise ImportError("yagura-tools-k8s requires 'kubernetes'") from exc
    if not _loaded:
        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        _loaded = True
    return client


def _core() -> Any:
    return _load_config().CoreV1Api()


def _apps() -> Any:
    return _load_config().AppsV1Api()


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _k8s_pod_list(namespace: str = "default", label_selector: str | None = None) -> ToolResult:
    pods = _core().list_namespaced_pod(namespace, label_selector=label_selector or "")
    return ToolResult(
        success=True,
        data={
            "pods": [
                {"name": p.metadata.name, "status": p.status.phase, "node": p.spec.node_name}
                for p in pods.items
            ],
            "count": len(pods.items),
        },
    )


def _k8s_pod_logs(name: str, namespace: str = "default", container: str | None = None, tail: int = 100) -> ToolResult:
    logs = _core().read_namespaced_pod_log(
        name=name, namespace=namespace, container=container, tail_lines=tail
    )
    return ToolResult(
        success=True,
        data={"pod": name, "logs": logs},
        reliability=ReliabilityLevel.AUTHORITATIVE,
    )


def _k8s_pod_exec(name: str, command: str, namespace: str = "default") -> ToolResult:
    from kubernetes.stream import stream  # type: ignore

    api = _core()
    result = stream(
        api.connect_get_namespaced_pod_exec,
        name,
        namespace,
        command=command.split() if isinstance(command, str) else command,
        stderr=True,
        stdin=False,
        stdout=True,
        tty=False,
    )
    return ToolResult(success=True, data={"pod": name, "output": result})


def _k8s_pod_delete(name: str, namespace: str = "default") -> ToolResult:
    _core().delete_namespaced_pod(name, namespace)
    return ToolResult(success=True, data={"pod": name, "namespace": namespace, "deleted": True})


def _k8s_deployment_list(namespace: str = "default") -> ToolResult:
    deps = _apps().list_namespaced_deployment(namespace)
    return ToolResult(
        success=True,
        data={
            "deployments": [
                {
                    "name": d.metadata.name,
                    "replicas": d.spec.replicas,
                    "ready": d.status.ready_replicas or 0,
                }
                for d in deps.items
            ],
        },
    )


def _k8s_deployment_create(name: str, image: str, replicas: int = 1, namespace: str = "default") -> ToolResult:
    client = _load_config()
    container = client.V1Container(name=name, image=image)
    template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels={"app": name}),
        spec=client.V1PodSpec(containers=[container]),
    )
    spec = client.V1DeploymentSpec(
        replicas=replicas,
        selector=client.V1LabelSelector(match_labels={"app": name}),
        template=template,
    )
    deployment = client.V1Deployment(
        metadata=client.V1ObjectMeta(name=name),
        spec=spec,
    )
    _apps().create_namespaced_deployment(namespace=namespace, body=deployment)
    return ToolResult(success=True, data={"name": name, "image": image, "replicas": replicas})


def _k8s_deployment_scale(name: str, replicas: int, namespace: str = "default") -> ToolResult:
    body = {"spec": {"replicas": replicas}}
    _apps().patch_namespaced_deployment_scale(name, namespace, body)
    return ToolResult(success=True, data={"name": name, "replicas": replicas})


def _k8s_deployment_rollback(name: str, namespace: str = "default") -> ToolResult:
    # Rollback by reverting to the previous revision via annotation.
    body = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {"kubernetes.io/change-cause": "rollback by yagura"}
                }
            }
        }
    }
    _apps().patch_namespaced_deployment(name, namespace, body)
    return ToolResult(success=True, data={"name": name, "rolled_back": True})


def _k8s_service_list(namespace: str = "default") -> ToolResult:
    services = _core().list_namespaced_service(namespace)
    return ToolResult(
        success=True,
        data={
            "services": [
                {
                    "name": s.metadata.name,
                    "type": s.spec.type,
                    "cluster_ip": s.spec.cluster_ip,
                    "ports": [{"port": p.port, "target_port": p.target_port} for p in (s.spec.ports or [])],
                }
                for s in services.items
            ],
        },
    )


def _k8s_service_create(name: str, port: int, target_port: int, namespace: str = "default") -> ToolResult:
    client = _load_config()
    service = client.V1Service(
        metadata=client.V1ObjectMeta(name=name),
        spec=client.V1ServiceSpec(
            selector={"app": name},
            ports=[client.V1ServicePort(port=port, target_port=target_port)],
        ),
    )
    _core().create_namespaced_service(namespace=namespace, body=service)
    return ToolResult(success=True, data={"name": name, "port": port, "target_port": target_port})


def _k8s_configmap_get(name: str, namespace: str = "default") -> ToolResult:
    cm = _core().read_namespaced_config_map(name, namespace)
    return ToolResult(
        success=True,
        data={"name": name, "data": cm.data or {}},
        reliability=ReliabilityLevel.AUTHORITATIVE,
    )


def _k8s_configmap_create(name: str, data: dict[str, str], namespace: str = "default") -> ToolResult:
    client = _load_config()
    body = client.V1ConfigMap(metadata=client.V1ObjectMeta(name=name), data=data)
    try:
        _core().create_namespaced_config_map(namespace=namespace, body=body)
    except Exception:
        _core().replace_namespaced_config_map(name=name, namespace=namespace, body=body)
    return ToolResult(success=True, data={"name": name, "keys": list(data.keys())})


def _k8s_secret_get(name: str, namespace: str = "default") -> ToolResult:
    s = _core().read_namespaced_secret(name, namespace)
    decoded = {k: base64.b64decode(v).decode("utf-8", errors="replace") for k, v in (s.data or {}).items()}
    return ToolResult(
        success=True,
        data={"name": name, "keys": list(decoded.keys()), "data": decoded},
        reliability=ReliabilityLevel.AUTHORITATIVE,
    )


def _k8s_secret_create(name: str, data: dict[str, str], namespace: str = "default") -> ToolResult:
    client = _load_config()
    encoded = {k: base64.b64encode(v.encode("utf-8")).decode("ascii") for k, v in data.items()}
    body = client.V1Secret(metadata=client.V1ObjectMeta(name=name), data=encoded)
    try:
        _core().create_namespaced_secret(namespace=namespace, body=body)
    except Exception:
        _core().replace_namespaced_secret(name=name, namespace=namespace, body=body)
    return ToolResult(success=True, data={"name": name, "keys": list(data.keys())})


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

_NS = {"type": "string", "description": "Namespace.", "default": "default"}


def _T(name: str, description: str, params: dict, handler, danger: DangerLevel | None, **extra) -> Tool:
    return Tool(
        name=name,
        description=description,
        parameters=params,
        handler=handler,
        danger_level=danger,
        tags=["k8s"],
        **extra,
    )


tools: list[Tool] = [
    _T(
        "k8s_pod_list",
        "List pods in a namespace.",
        {
            "type": "object",
            "properties": {"namespace": _NS, "label_selector": {"type": "string"}},
            "required": [],
        },
        _k8s_pod_list,
        DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE,
    ),
    _T(
        "k8s_pod_logs",
        "Fetch pod logs.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "namespace": _NS,
                "container": {"type": "string"},
                "tail": {"type": "integer", "default": 100},
            },
            "required": ["name"],
        },
        _k8s_pod_logs,
        DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE,
    ),
    _T(
        "k8s_pod_exec",
        "Execute a command in a pod.",
        {
            "type": "object",
            "properties": {"name": {"type": "string"}, "namespace": _NS, "command": {"type": "string"}},
            "required": ["name", "command"],
        },
        _k8s_pod_exec,
        None,
        requires_llm=True,
    ),
    _T(
        "k8s_pod_delete",
        "Delete a pod.",
        {
            "type": "object",
            "properties": {"name": {"type": "string"}, "namespace": _NS},
            "required": ["name"],
        },
        _k8s_pod_delete,
        DangerLevel.DESTRUCTIVE,
    ),
    _T(
        "k8s_deployment_list",
        "List deployments in a namespace.",
        {"type": "object", "properties": {"namespace": _NS}, "required": []},
        _k8s_deployment_list,
        DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE,
    ),
    _T(
        "k8s_deployment_create",
        "Create a deployment.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "image": {"type": "string"},
                "replicas": {"type": "integer", "default": 1},
                "namespace": _NS,
            },
            "required": ["name", "image"],
        },
        _k8s_deployment_create,
        DangerLevel.MODIFY,
    ),
    _T(
        "k8s_deployment_scale",
        "Scale a deployment's replica count.",
        {
            "type": "object",
            "properties": {"name": {"type": "string"}, "replicas": {"type": "integer"}, "namespace": _NS},
            "required": ["name", "replicas"],
        },
        _k8s_deployment_scale,
        DangerLevel.MODIFY,
    ),
    _T(
        "k8s_deployment_rollback",
        "Roll back a deployment. DESTRUCTIVE.",
        {
            "type": "object",
            "properties": {"name": {"type": "string"}, "namespace": _NS},
            "required": ["name"],
        },
        _k8s_deployment_rollback,
        DangerLevel.DESTRUCTIVE,
    ),
    _T(
        "k8s_service_list",
        "List services in a namespace.",
        {"type": "object", "properties": {"namespace": _NS}, "required": []},
        _k8s_service_list,
        DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE,
    ),
    _T(
        "k8s_service_create",
        "Create a service.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "port": {"type": "integer"},
                "target_port": {"type": "integer"},
                "namespace": _NS,
            },
            "required": ["name", "port", "target_port"],
        },
        _k8s_service_create,
        DangerLevel.MODIFY,
    ),
    _T(
        "k8s_configmap_get",
        "Get a ConfigMap.",
        {
            "type": "object",
            "properties": {"name": {"type": "string"}, "namespace": _NS},
            "required": ["name"],
        },
        _k8s_configmap_get,
        DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE,
    ),
    _T(
        "k8s_configmap_create",
        "Create or update a ConfigMap.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "data": {"type": "object"},
                "namespace": _NS,
            },
            "required": ["name", "data"],
        },
        _k8s_configmap_create,
        DangerLevel.MODIFY,
    ),
    _T(
        "k8s_secret_get",
        "Get a Secret (values base64-decoded).",
        {
            "type": "object",
            "properties": {"name": {"type": "string"}, "namespace": _NS},
            "required": ["name"],
        },
        _k8s_secret_get,
        DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE,
    ),
    _T(
        "k8s_secret_create",
        "Create or update a Secret.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "data": {"type": "object"},
                "namespace": _NS,
            },
            "required": ["name", "data"],
        },
        _k8s_secret_create,
        DangerLevel.MODIFY,
    ),
]

__all__ = ["tools"]
