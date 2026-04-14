"""yagura-tools-aws — S3, Lambda, SQS, Step Functions, Bedrock."""

from __future__ import annotations

import json
from typing import Any

from yagura import DangerLevel, Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


def _boto3():
    try:
        import boto3  # type: ignore
    except ImportError as exc:
        raise ImportError("yagura-tools-aws requires 'boto3'") from exc
    return boto3


# ---------------------------------------------------------------------------
# S3
# ---------------------------------------------------------------------------


def _s3_list(bucket: str, prefix: str | None = None) -> ToolResult:
    client = _boto3().client("s3")
    kwargs: dict[str, Any] = {"Bucket": bucket}
    if prefix:
        kwargs["Prefix"] = prefix
    response = client.list_objects_v2(**kwargs)
    objects = [
        {"key": o["Key"], "size": o["Size"], "modified": o["LastModified"].isoformat()}
        for o in response.get("Contents", [])
    ]
    return ToolResult(success=True, data={"bucket": bucket, "objects": objects, "count": len(objects)})


def _s3_download(bucket: str, key: str, local_path: str) -> ToolResult:
    client = _boto3().client("s3")
    client.download_file(bucket, key, local_path)
    return ToolResult(success=True, data={"bucket": bucket, "key": key, "local_path": local_path})


def _s3_upload(local_path: str, bucket: str, key: str) -> ToolResult:
    client = _boto3().client("s3")
    client.upload_file(local_path, bucket, key)
    return ToolResult(success=True, data={"bucket": bucket, "key": key, "local_path": local_path})


def _s3_delete(bucket: str, key: str) -> ToolResult:
    client = _boto3().client("s3")
    client.delete_object(Bucket=bucket, Key=key)
    return ToolResult(success=True, data={"bucket": bucket, "key": key, "deleted": True})


# ---------------------------------------------------------------------------
# Lambda
# ---------------------------------------------------------------------------


def _lambda_invoke(function_name: str, payload: dict[str, Any] | None = None) -> ToolResult:
    client = _boto3().client("lambda")
    response = client.invoke(
        FunctionName=function_name,
        Payload=json.dumps(payload or {}).encode("utf-8"),
    )
    body = response["Payload"].read().decode("utf-8", errors="replace")
    try:
        parsed: Any = json.loads(body)
    except json.JSONDecodeError:
        parsed = body
    return ToolResult(
        success=response.get("StatusCode", 500) < 300,
        data={"status": response.get("StatusCode"), "result": parsed},
    )


def _lambda_list(region: str | None = None) -> ToolResult:
    client = _boto3().client("lambda", region_name=region)
    functions = client.list_functions().get("Functions", [])
    return ToolResult(
        success=True,
        data={"functions": [{"name": f["FunctionName"], "runtime": f.get("Runtime")} for f in functions]},
    )


# ---------------------------------------------------------------------------
# SQS
# ---------------------------------------------------------------------------


def _sqs_send(queue_url: str, message: str, attributes: dict | None = None) -> ToolResult:
    client = _boto3().client("sqs")
    kwargs: dict[str, Any] = {"QueueUrl": queue_url, "MessageBody": message}
    if attributes:
        kwargs["MessageAttributes"] = attributes
    response = client.send_message(**kwargs)
    return ToolResult(success=True, data={"message_id": response.get("MessageId")})


def _sqs_receive(queue_url: str, max_messages: int = 1) -> ToolResult:
    client = _boto3().client("sqs")
    response = client.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=max_messages)
    return ToolResult(
        success=True,
        data={"messages": response.get("Messages", [])},
    )


def _sqs_delete_message(queue_url: str, receipt_handle: str) -> ToolResult:
    client = _boto3().client("sqs")
    client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
    return ToolResult(success=True, data={"deleted": True})


# ---------------------------------------------------------------------------
# Step Functions
# ---------------------------------------------------------------------------


def _stepfunctions_start(state_machine_arn: str, input: dict | None = None) -> ToolResult:
    client = _boto3().client("stepfunctions")
    response = client.start_execution(
        stateMachineArn=state_machine_arn,
        input=json.dumps(input or {}),
    )
    return ToolResult(
        success=True,
        data={
            "execution_arn": response["executionArn"],
            "started_at": response["startDate"].isoformat(),
        },
    )


def _stepfunctions_status(execution_arn: str) -> ToolResult:
    client = _boto3().client("stepfunctions")
    response = client.describe_execution(executionArn=execution_arn)
    return ToolResult(
        success=True,
        data={
            "status": response["status"],
            "started_at": response["startDate"].isoformat(),
            "stopped_at": response.get("stopDate").isoformat() if response.get("stopDate") else None,
        },
    )


# ---------------------------------------------------------------------------
# Bedrock
# ---------------------------------------------------------------------------


def _bedrock_invoke(model_id: str, prompt: str, params: dict | None = None) -> ToolResult:
    """Invoke a Bedrock model.

    Bedrock bodies differ per model family. We route on `model_id` prefix.
    Callers can fully override by passing a `body` key in `params`.
    """
    client = _boto3().client("bedrock-runtime")
    params = dict(params or {})
    override_body = params.pop("body", None)
    body_dict = override_body if override_body is not None else _bedrock_body_for(model_id, prompt, params)

    response = client.invoke_model(modelId=model_id, body=json.dumps(body_dict))
    raw = response["body"].read().decode("utf-8", errors="replace")
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError:
        parsed = raw

    generated_text = _bedrock_extract_text(model_id, parsed)
    return ToolResult(
        success=True,
        data={"model_id": model_id, "text": generated_text, "raw": parsed},
    )


def _bedrock_body_for(model_id: str, prompt: str, params: dict[str, Any]) -> dict[str, Any]:
    """Return a Bedrock invoke_model body tailored to the model family."""
    mid = model_id.lower()

    # Anthropic Claude on Bedrock (Messages API).
    if mid.startswith("anthropic.") or "claude" in mid:
        return {
            "anthropic_version": params.get("anthropic_version", "bedrock-2023-05-31"),
            "max_tokens": params.get("max_tokens", 1024),
            "messages": params.get("messages") or [{"role": "user", "content": prompt}],
            **{k: v for k, v in params.items() if k not in {"max_tokens", "messages", "anthropic_version"}},
        }

    # Amazon Titan.
    if mid.startswith("amazon.titan"):
        return {
            "inputText": prompt,
            "textGenerationConfig": {
                "maxTokenCount": params.get("max_tokens", 512),
                "temperature": params.get("temperature", 0.7),
                "topP": params.get("top_p", 0.9),
                **(params.get("textGenerationConfig") or {}),
            },
        }

    # Meta Llama.
    if mid.startswith("meta.llama"):
        return {
            "prompt": prompt,
            "max_gen_len": params.get("max_tokens", 512),
            "temperature": params.get("temperature", 0.7),
            "top_p": params.get("top_p", 0.9),
        }

    # AI21.
    if mid.startswith("ai21."):
        return {
            "prompt": prompt,
            "maxTokens": params.get("max_tokens", 512),
            "temperature": params.get("temperature", 0.7),
            **{k: v for k, v in params.items() if k not in {"max_tokens", "temperature"}},
        }

    # Cohere.
    if mid.startswith("cohere."):
        return {
            "prompt": prompt,
            "max_tokens": params.get("max_tokens", 512),
            "temperature": params.get("temperature", 0.7),
            **{k: v for k, v in params.items() if k not in {"max_tokens", "temperature"}},
        }

    # Mistral.
    if mid.startswith("mistral."):
        return {
            "prompt": prompt,
            "max_tokens": params.get("max_tokens", 512),
            "temperature": params.get("temperature", 0.7),
            **{k: v for k, v in params.items() if k not in {"max_tokens", "temperature"}},
        }

    # Unknown family: generic fallback.
    return {"prompt": prompt, **params}


def _bedrock_extract_text(model_id: str, parsed: Any) -> str:
    """Pull the generated text out of a parsed Bedrock response."""
    if not isinstance(parsed, dict):
        return str(parsed)
    mid = model_id.lower()
    if mid.startswith("anthropic.") or "claude" in mid:
        content = parsed.get("content") or []
        if isinstance(content, list) and content and isinstance(content[0], dict):
            return content[0].get("text", "") or ""
        return ""
    if mid.startswith("amazon.titan"):
        results = parsed.get("results") or []
        if results and isinstance(results[0], dict):
            return results[0].get("outputText", "") or ""
        return ""
    if mid.startswith("meta.llama"):
        return parsed.get("generation", "") or ""
    if mid.startswith("ai21."):
        completions = parsed.get("completions") or []
        if completions and isinstance(completions[0], dict):
            return completions[0].get("data", {}).get("text", "") or ""
        return ""
    if mid.startswith("cohere."):
        generations = parsed.get("generations") or []
        if generations and isinstance(generations[0], dict):
            return generations[0].get("text", "") or ""
        return ""
    if mid.startswith("mistral."):
        outputs = parsed.get("outputs") or []
        if outputs and isinstance(outputs[0], dict):
            return outputs[0].get("text", "") or ""
        return ""
    for key in ("output", "completion", "text", "result"):
        if key in parsed and isinstance(parsed[key], str):
            return parsed[key]
    return ""


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


def _T(name, description, props, required, handler, danger, **extra):
    return Tool(
        name=name,
        description=description,
        parameters={"type": "object", "properties": props, "required": required},
        handler=handler,
        danger_level=danger,
        tags=["aws"],
        **extra,
    )


tools: list[Tool] = [
    _T(
        "s3_list",
        "List S3 objects.",
        {"bucket": {"type": "string"}, "prefix": {"type": "string"}},
        ["bucket"],
        _s3_list,
        DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE,
    ),
    _T(
        "s3_download",
        "Download a file from S3.",
        {
            "bucket": {"type": "string"},
            "key": {"type": "string"},
            "local_path": {"type": "string"},
        },
        ["bucket", "key", "local_path"],
        _s3_download,
        DangerLevel.READ,
    ),
    _T(
        "s3_upload",
        "Upload a file to S3.",
        {
            "local_path": {"type": "string"},
            "bucket": {"type": "string"},
            "key": {"type": "string"},
        },
        ["local_path", "bucket", "key"],
        _s3_upload,
        DangerLevel.MODIFY,
    ),
    _T(
        "s3_delete",
        "Delete an S3 object.",
        {"bucket": {"type": "string"}, "key": {"type": "string"}},
        ["bucket", "key"],
        _s3_delete,
        DangerLevel.DESTRUCTIVE,
    ),
    _T(
        "lambda_invoke",
        "Invoke a Lambda function.",
        {"function_name": {"type": "string"}, "payload": {"type": "object"}},
        ["function_name"],
        _lambda_invoke,
        DangerLevel.MODIFY,
    ),
    _T(
        "lambda_list",
        "List Lambda functions.",
        {"region": {"type": "string"}},
        [],
        _lambda_list,
        DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE,
    ),
    _T(
        "sqs_send",
        "Send a message to an SQS queue.",
        {
            "queue_url": {"type": "string"},
            "message": {"type": "string"},
            "attributes": {"type": "object"},
        },
        ["queue_url", "message"],
        _sqs_send,
        DangerLevel.MODIFY,
    ),
    _T(
        "sqs_receive",
        "Receive SQS messages.",
        {"queue_url": {"type": "string"}, "max_messages": {"type": "integer", "default": 1}},
        ["queue_url"],
        _sqs_receive,
        DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE,
    ),
    _T(
        "sqs_delete_message",
        "Delete an SQS message.",
        {"queue_url": {"type": "string"}, "receipt_handle": {"type": "string"}},
        ["queue_url", "receipt_handle"],
        _sqs_delete_message,
        DangerLevel.MODIFY,
    ),
    _T(
        "stepfunctions_start",
        "Start a Step Functions execution.",
        {"state_machine_arn": {"type": "string"}, "input": {"type": "object"}},
        ["state_machine_arn"],
        _stepfunctions_start,
        DangerLevel.MODIFY,
    ),
    _T(
        "stepfunctions_status",
        "Get the status of a Step Functions execution.",
        {"execution_arn": {"type": "string"}},
        ["execution_arn"],
        _stepfunctions_status,
        DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE,
    ),
    _T(
        "bedrock_invoke",
        "Invoke a Bedrock model.",
        {
            "model_id": {"type": "string"},
            "prompt": {"type": "string"},
            "params": {"type": "object"},
        },
        ["model_id", "prompt"],
        _bedrock_invoke,
        DangerLevel.MODIFY,
    ),
]

__all__ = ["tools"]
