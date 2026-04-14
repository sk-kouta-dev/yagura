"""yagura-tools-llm — LLM capabilities exposed as Tools.

All tools here use the LLM-as-tool execution path: `Tool.llm_task_template`
is set to a natural-language instruction that the executor LLM evaluates
directly. The handler is never invoked; the LLM's response text becomes
`ToolResult.data[output_key]`.

This replaces the earlier "populate the `result` field" convention, which
relied on the executor LLM understanding an implicit protocol. With
`llm_task_template`, the instruction is explicit and the LLM has exactly
one job: produce text.

Reliability defaults to REFERENCE — the framework auto-inserts a
confirmation step before a later plan step consumes LLM output.
"""

from __future__ import annotations

from yagura import DangerLevel, Tool
from yagura.safety.reliability import ReliabilityLevel


def _llm_tool(
    name: str,
    description: str,
    template: str,
    properties: dict,
    required: list[str],
    output_key: str,
) -> Tool:
    return Tool(
        name=name,
        description=description,
        parameters={"type": "object", "properties": properties, "required": required},
        # Handler is never called for LLM-as-tool; a no-op placeholder keeps
        # ToolRegistry registration invariants intact.
        handler=lambda **_: None,
        danger_level=DangerLevel.READ,
        default_reliability=ReliabilityLevel.REFERENCE,
        tags=["llm"],
        llm_task_template=template,
        llm_output_key=output_key,
    )


llm_summarize = _llm_tool(
    "llm_summarize",
    "Summarize text.",
    template=(
        "Summarize the following text in no more than {max_length} words.\n"
        "Style: {style}.\n\n"
        "---\n"
        "{text}\n"
        "---\n\n"
        "Respond with only the summary, no preamble."
    ),
    properties={
        "text": {"type": "string"},
        "max_length": {"type": "integer", "default": 200},
        "style": {"type": "string", "default": "concise"},
    },
    required=["text"],
    output_key="summary",
)


llm_translate = _llm_tool(
    "llm_translate",
    "Translate text to another language.",
    template=(
        "Translate the following text from {source_language} to {target_language}.\n"
        "Preserve tone and formatting.\n\n"
        "---\n"
        "{text}\n"
        "---\n\n"
        "Respond with only the translation, no preamble."
    ),
    properties={
        "text": {"type": "string"},
        "target_language": {"type": "string"},
        "source_language": {"type": "string", "default": "auto-detect"},
    },
    required=["text", "target_language"],
    output_key="translation",
)


llm_extract_entities = _llm_tool(
    "llm_extract_entities",
    "Extract named entities from text.",
    template=(
        "Extract named entities from the text below.\n"
        "Entity types to find: {entity_types}\n\n"
        "---\n"
        "{text}\n"
        "---\n\n"
        "Respond with a single JSON array like "
        '[{{"type": "person", "name": "Alice"}}]. No prose.'
    ),
    properties={
        "text": {"type": "string"},
        "entity_types": {
            "type": "array",
            "items": {"type": "string"},
            "default": ["person", "organization", "location", "date"],
        },
    },
    required=["text"],
    output_key="entities",
)


llm_classify = _llm_tool(
    "llm_classify",
    "Classify text into one of the given categories.",
    template=(
        "Classify the text below into exactly one of these categories: {categories}\n\n"
        "---\n"
        "{text}\n"
        "---\n\n"
        "Respond with only the single category name from the list above."
    ),
    properties={
        "text": {"type": "string"},
        "categories": {"type": "array", "items": {"type": "string"}},
    },
    required=["text", "categories"],
    output_key="category",
)


llm_sentiment = _llm_tool(
    "llm_sentiment",
    "Analyze sentiment (positive / neutral / negative).",
    template=(
        "Analyze the sentiment of the text below. Respond with ONE word: "
        "positive, neutral, or negative.\n\n"
        "---\n"
        "{text}\n"
        "---"
    ),
    properties={"text": {"type": "string"}},
    required=["text"],
    output_key="sentiment",
)


llm_generate_code = _llm_tool(
    "llm_generate_code",
    "Generate code from a natural-language description.",
    template=(
        "Write {language} code that does the following:\n"
        "{description}\n\n"
        "Respond with ONLY the code. No explanation, no markdown fences."
    ),
    properties={
        "description": {"type": "string"},
        "language": {"type": "string"},
    },
    required=["description", "language"],
    output_key="code",
)


llm_explain_code = _llm_tool(
    "llm_explain_code",
    "Explain what a piece of code does.",
    template=(
        "Explain what this {language} code does. Keep the explanation concise.\n\n"
        "```\n{code}\n```\n\n"
        "Respond with the explanation only."
    ),
    properties={
        "code": {"type": "string"},
        "language": {"type": "string", "default": "auto-detect"},
    },
    required=["code"],
    output_key="explanation",
)


llm_rewrite = _llm_tool(
    "llm_rewrite",
    "Rewrite text in a different style.",
    template=(
        "Rewrite the text below in a {style} style. Preserve the meaning.\n\n"
        "---\n"
        "{text}\n"
        "---\n\n"
        "Respond with only the rewritten text."
    ),
    properties={
        "text": {"type": "string"},
        "style": {"type": "string"},
    },
    required=["text", "style"],
    output_key="rewritten",
)


tools: list[Tool] = [
    llm_summarize,
    llm_translate,
    llm_extract_entities,
    llm_classify,
    llm_sentiment,
    llm_generate_code,
    llm_explain_code,
    llm_rewrite,
]

__all__ = ["tools"]
