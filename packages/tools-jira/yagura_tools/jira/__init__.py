"""yagura-tools-jira — Atlassian Jira Cloud/Server.

Credentials: set `JIRA_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` in the environment,
or pass them per-call.
"""

from __future__ import annotations

import os
from typing import Any

from yagura import DangerLevel, Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


def _client(url: str | None = None, email: str | None = None, token: str | None = None):
    try:
        from jira import JIRA  # type: ignore
    except ImportError as exc:
        raise ImportError("yagura-tools-jira requires 'jira'") from exc
    url = url or os.environ.get("JIRA_URL")
    email = email or os.environ.get("JIRA_EMAIL")
    token = token or os.environ.get("JIRA_API_TOKEN")
    if not (url and email and token):
        raise RuntimeError("Set JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN or pass them explicitly.")
    return JIRA(server=url, basic_auth=(email, token))


def _issue_to_dict(issue) -> dict[str, Any]:
    return {
        "key": issue.key,
        "summary": issue.fields.summary,
        "status": issue.fields.status.name if issue.fields.status else None,
        "assignee": issue.fields.assignee.displayName if issue.fields.assignee else None,
        "issuetype": issue.fields.issuetype.name if issue.fields.issuetype else None,
    }


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _jira_issue_search(jql: str, max_results: int = 50, **auth) -> ToolResult:
    issues = _client(**auth).search_issues(jql, maxResults=max_results)
    return ToolResult(
        success=True,
        data={"issues": [_issue_to_dict(i) for i in issues], "count": len(issues)},
        reliability=ReliabilityLevel.AUTHORITATIVE,
    )


def _jira_issue_get(issue_key: str, **auth) -> ToolResult:
    issue = _client(**auth).issue(issue_key)
    return ToolResult(
        success=True,
        data={**_issue_to_dict(issue), "description": issue.fields.description},
        reliability=ReliabilityLevel.AUTHORITATIVE,
    )


def _jira_issue_create(project: str, summary: str, issue_type: str, description: str | None = None, **auth) -> ToolResult:
    issue = _client(**auth).create_issue(
        project=project, summary=summary, issuetype={"name": issue_type}, description=description or ""
    )
    return ToolResult(success=True, data={"key": issue.key})


def _jira_issue_update(issue_key: str, fields: dict[str, Any], **auth) -> ToolResult:
    _client(**auth).issue(issue_key).update(fields=fields)
    return ToolResult(success=True, data={"key": issue_key, "updated": list(fields.keys())})


def _jira_issue_delete(issue_key: str, **auth) -> ToolResult:
    _client(**auth).issue(issue_key).delete()
    return ToolResult(success=True, data={"key": issue_key, "deleted": True})


def _jira_issue_transition(issue_key: str, transition: str, **auth) -> ToolResult:
    client = _client(**auth)
    transitions = client.transitions(issue_key)
    match = next((t for t in transitions if t["name"].lower() == transition.lower()), None)
    if not match:
        return ToolResult(success=False, error=f"Transition '{transition}' not available", data={"available": [t["name"] for t in transitions]})
    client.transition_issue(issue_key, match["id"])
    return ToolResult(success=True, data={"key": issue_key, "transition": transition})


def _jira_comment_add(issue_key: str, body: str, **auth) -> ToolResult:
    comment = _client(**auth).add_comment(issue_key, body)
    return ToolResult(success=True, data={"comment_id": comment.id})


def _jira_comment_list(issue_key: str, **auth) -> ToolResult:
    comments = _client(**auth).comments(issue_key)
    return ToolResult(
        success=True,
        data={
            "comments": [
                {"id": c.id, "author": c.author.displayName, "body": c.body, "created": c.created}
                for c in comments
            ],
        },
    )


def _jira_sprint_list(board_id: int, **auth) -> ToolResult:
    sprints = _client(**auth).sprints(board_id)
    return ToolResult(success=True, data={"sprints": [{"id": s.id, "name": s.name, "state": s.state} for s in sprints]})


def _jira_sprint_issues(sprint_id: int, **auth) -> ToolResult:
    issues = _client(**auth).search_issues(f"sprint = {sprint_id}")
    return ToolResult(success=True, data={"issues": [_issue_to_dict(i) for i in issues]})


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


_AUTH = {
    "url": {"type": "string", "description": "Jira URL (defaults to $JIRA_URL)."},
    "email": {"type": "string", "description": "Jira email."},
    "token": {"type": "string", "description": "Jira API token."},
}


def _T(name, description, props, required, handler, danger, **extra):
    return Tool(
        name=name, description=description,
        parameters={"type": "object", "properties": {**_AUTH, **props}, "required": required},
        handler=handler, danger_level=danger, tags=["jira"], **extra,
    )


tools: list[Tool] = [
    _T("jira_issue_search", "Search issues with JQL.",
        {"jql": {"type": "string"}, "max_results": {"type": "integer", "default": 50}},
        ["jql"], _jira_issue_search, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("jira_issue_get", "Get a single issue.",
        {"issue_key": {"type": "string"}},
        ["issue_key"], _jira_issue_get, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("jira_issue_create", "Create an issue.",
        {"project": {"type": "string"}, "summary": {"type": "string"}, "issue_type": {"type": "string"}, "description": {"type": "string"}},
        ["project", "summary", "issue_type"], _jira_issue_create, DangerLevel.MODIFY),
    _T("jira_issue_update", "Update issue fields.",
        {"issue_key": {"type": "string"}, "fields": {"type": "object"}},
        ["issue_key", "fields"], _jira_issue_update, DangerLevel.MODIFY),
    _T("jira_issue_delete", "Delete an issue. DESTRUCTIVE.",
        {"issue_key": {"type": "string"}},
        ["issue_key"], _jira_issue_delete, DangerLevel.DESTRUCTIVE),
    _T("jira_issue_transition", "Change an issue's status.",
        {"issue_key": {"type": "string"}, "transition": {"type": "string"}},
        ["issue_key", "transition"], _jira_issue_transition, DangerLevel.MODIFY),
    _T("jira_comment_add", "Add a comment.",
        {"issue_key": {"type": "string"}, "body": {"type": "string"}},
        ["issue_key", "body"], _jira_comment_add, DangerLevel.MODIFY),
    _T("jira_comment_list", "List comments on an issue.",
        {"issue_key": {"type": "string"}},
        ["issue_key"], _jira_comment_list, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("jira_sprint_list", "List sprints for a board.",
        {"board_id": {"type": "integer"}},
        ["board_id"], _jira_sprint_list, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
    _T("jira_sprint_issues", "Get issues in a sprint.",
        {"sprint_id": {"type": "integer"}},
        ["sprint_id"], _jira_sprint_issues, DangerLevel.READ,
        default_reliability=ReliabilityLevel.AUTHORITATIVE),
]

__all__ = ["tools"]
