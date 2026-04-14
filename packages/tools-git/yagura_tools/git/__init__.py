"""yagura-tools-git — Git operations via GitPython.

Usage:
    from yagura_tools.git import tools
    agent.register_tools(tools)
"""

from __future__ import annotations

import os
from typing import Any

from yagura import DangerLevel, Tool, ToolResult
from yagura.safety.reliability import ReliabilityLevel


def _lazy_git() -> Any:
    try:
        import git  # type: ignore
    except ImportError as exc:
        raise ImportError("yagura-tools-git requires 'gitpython'") from exc
    return git


def _resolve_repo_path(repo_path: str | None) -> str:
    return repo_path or os.getcwd()


def _git_status(repo_path: str | None = None) -> ToolResult:
    git = _lazy_git()
    repo = git.Repo(_resolve_repo_path(repo_path))
    return ToolResult(
        success=True,
        data={
            "branch": repo.active_branch.name if not repo.head.is_detached else None,
            "dirty": repo.is_dirty(untracked_files=True),
            "untracked": repo.untracked_files,
            "modified": [item.a_path for item in repo.index.diff(None)],
            "staged": [item.a_path for item in repo.index.diff("HEAD")] if repo.head.is_valid() else [],
        },
    )


def _git_log(repo_path: str | None = None, n: int = 10) -> ToolResult:
    git = _lazy_git()
    repo = git.Repo(_resolve_repo_path(repo_path))
    commits = []
    for commit in repo.iter_commits(max_count=n):
        commits.append(
            {
                "sha": commit.hexsha,
                "short": commit.hexsha[:7],
                "author": f"{commit.author.name} <{commit.author.email}>",
                "date": commit.authored_datetime.isoformat(),
                "message": commit.message.strip(),
            }
        )
    return ToolResult(success=True, data={"commits": commits})


def _git_diff(repo_path: str | None = None, staged: bool = False) -> ToolResult:
    git = _lazy_git()
    repo = git.Repo(_resolve_repo_path(repo_path))
    args = ["--cached"] if staged else []
    diff = repo.git.diff(*args)
    return ToolResult(success=True, data={"diff": diff, "staged": staged})


def _git_add(files: list[str], repo_path: str | None = None) -> ToolResult:
    git = _lazy_git()
    repo = git.Repo(_resolve_repo_path(repo_path))
    repo.index.add(files)
    return ToolResult(success=True, data={"added": files})


def _git_commit(message: str, repo_path: str | None = None) -> ToolResult:
    git = _lazy_git()
    repo = git.Repo(_resolve_repo_path(repo_path))
    commit = repo.index.commit(message)
    return ToolResult(
        success=True,
        data={"sha": commit.hexsha, "short": commit.hexsha[:7], "message": message},
    )


def _git_push(repo_path: str | None = None, remote: str = "origin", branch: str | None = None) -> ToolResult:
    git = _lazy_git()
    repo = git.Repo(_resolve_repo_path(repo_path))
    refspec = branch or (repo.active_branch.name if not repo.head.is_detached else None)
    push_info = repo.remote(remote).push(refspec=refspec)
    return ToolResult(
        success=all(info.flags & info.ERROR == 0 for info in push_info),
        data={
            "remote": remote,
            "refspec": refspec,
            "summary": [info.summary.strip() for info in push_info],
        },
    )


def _git_pull(repo_path: str | None = None, remote: str = "origin", branch: str | None = None) -> ToolResult:
    git = _lazy_git()
    repo = git.Repo(_resolve_repo_path(repo_path))
    refspec = branch or (repo.active_branch.name if not repo.head.is_detached else None)
    pull_info = repo.remote(remote).pull(refspec=refspec)
    return ToolResult(
        success=True,
        data={"remote": remote, "refspec": refspec, "summary": [str(i) for i in pull_info]},
    )


def _git_branch_create(name: str, repo_path: str | None = None, checkout: bool = False) -> ToolResult:
    git = _lazy_git()
    repo = git.Repo(_resolve_repo_path(repo_path))
    new_branch = repo.create_head(name)
    if checkout:
        new_branch.checkout()
    return ToolResult(success=True, data={"branch": name, "checkout": checkout})


def _git_branch_list(repo_path: str | None = None) -> ToolResult:
    git = _lazy_git()
    repo = git.Repo(_resolve_repo_path(repo_path))
    current = repo.active_branch.name if not repo.head.is_detached else None
    branches = [h.name for h in repo.heads]
    return ToolResult(success=True, data={"current": current, "branches": branches})


def _git_checkout(branch: str, repo_path: str | None = None) -> ToolResult:
    git = _lazy_git()
    repo = git.Repo(_resolve_repo_path(repo_path))
    repo.git.checkout(branch)
    return ToolResult(success=True, data={"branch": branch})


def _git_merge(branch: str, repo_path: str | None = None) -> ToolResult:
    git = _lazy_git()
    repo = git.Repo(_resolve_repo_path(repo_path))
    repo.git.merge(branch)
    return ToolResult(success=True, data={"merged": branch})


def _git_create_pr(repo: str, title: str, body: str, head: str, base: str, token: str | None = None) -> ToolResult:
    """Create a GitHub pull request. Requires PyGithub + a token via param or $GITHUB_TOKEN."""
    try:
        from github import Github  # type: ignore
    except ImportError as exc:
        raise ImportError("git_create_pr requires the [github] extra: pip install yagura-tools-git[github]") from exc
    gh = Github(token or os.environ.get("GITHUB_TOKEN"))
    gh_repo = gh.get_repo(repo)
    pr = gh_repo.create_pull(title=title, body=body, head=head, base=base)
    return ToolResult(
        success=True,
        data={"number": pr.number, "url": pr.html_url, "title": title},
    )


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


_REPO_PATH = {"type": "string", "description": "Path to the repository. Defaults to CWD."}


git_status = Tool(
    name="git_status",
    description="Show repository status (current branch, modified/staged/untracked files).",
    parameters={"type": "object", "properties": {"repo_path": _REPO_PATH}, "required": []},
    handler=_git_status,
    danger_level=DangerLevel.READ,
    default_reliability=ReliabilityLevel.AUTHORITATIVE,
    tags=["git"],
)

git_log = Tool(
    name="git_log",
    description="List recent commits.",
    parameters={
        "type": "object",
        "properties": {"repo_path": _REPO_PATH, "n": {"type": "integer", "default": 10}},
        "required": [],
    },
    handler=_git_log,
    danger_level=DangerLevel.READ,
    default_reliability=ReliabilityLevel.AUTHORITATIVE,
    tags=["git"],
)

git_diff = Tool(
    name="git_diff",
    description="Show uncommitted diff (staged=True for index diff).",
    parameters={
        "type": "object",
        "properties": {"repo_path": _REPO_PATH, "staged": {"type": "boolean", "default": False}},
        "required": [],
    },
    handler=_git_diff,
    danger_level=DangerLevel.READ,
    default_reliability=ReliabilityLevel.AUTHORITATIVE,
    tags=["git"],
)

git_add = Tool(
    name="git_add",
    description="Stage files for commit.",
    parameters={
        "type": "object",
        "properties": {
            "repo_path": _REPO_PATH,
            "files": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["files"],
    },
    handler=_git_add,
    danger_level=DangerLevel.MODIFY,
    tags=["git"],
)

git_commit = Tool(
    name="git_commit",
    description="Create a commit from the staged index.",
    parameters={
        "type": "object",
        "properties": {"repo_path": _REPO_PATH, "message": {"type": "string"}},
        "required": ["message"],
    },
    handler=_git_commit,
    danger_level=DangerLevel.MODIFY,
    tags=["git"],
)

git_push = Tool(
    name="git_push",
    description="Push to a remote. DESTRUCTIVE because it affects shared state.",
    parameters={
        "type": "object",
        "properties": {
            "repo_path": _REPO_PATH,
            "remote": {"type": "string", "default": "origin"},
            "branch": {"type": "string"},
        },
        "required": [],
    },
    handler=_git_push,
    danger_level=DangerLevel.DESTRUCTIVE,
    tags=["git"],
)

git_pull = Tool(
    name="git_pull",
    description="Pull changes from a remote.",
    parameters={
        "type": "object",
        "properties": {
            "repo_path": _REPO_PATH,
            "remote": {"type": "string", "default": "origin"},
            "branch": {"type": "string"},
        },
        "required": [],
    },
    handler=_git_pull,
    danger_level=DangerLevel.MODIFY,
    tags=["git"],
)

git_branch_create = Tool(
    name="git_branch_create",
    description="Create a new branch.",
    parameters={
        "type": "object",
        "properties": {
            "repo_path": _REPO_PATH,
            "name": {"type": "string"},
            "checkout": {"type": "boolean", "default": False},
        },
        "required": ["name"],
    },
    handler=_git_branch_create,
    danger_level=DangerLevel.MODIFY,
    tags=["git"],
)

git_branch_list = Tool(
    name="git_branch_list",
    description="List local branches.",
    parameters={"type": "object", "properties": {"repo_path": _REPO_PATH}, "required": []},
    handler=_git_branch_list,
    danger_level=DangerLevel.READ,
    default_reliability=ReliabilityLevel.AUTHORITATIVE,
    tags=["git"],
)

git_checkout = Tool(
    name="git_checkout",
    description="Switch to a branch.",
    parameters={
        "type": "object",
        "properties": {"repo_path": _REPO_PATH, "branch": {"type": "string"}},
        "required": ["branch"],
    },
    handler=_git_checkout,
    danger_level=DangerLevel.MODIFY,
    tags=["git"],
)

git_merge = Tool(
    name="git_merge",
    description="Merge a branch into the current branch. DESTRUCTIVE — may affect history.",
    parameters={
        "type": "object",
        "properties": {"repo_path": _REPO_PATH, "branch": {"type": "string"}},
        "required": ["branch"],
    },
    handler=_git_merge,
    danger_level=DangerLevel.DESTRUCTIVE,
    tags=["git"],
)

git_create_pr = Tool(
    name="git_create_pr",
    description="Create a GitHub pull request. Requires the [github] extra.",
    parameters={
        "type": "object",
        "properties": {
            "repo": {"type": "string", "description": "owner/repo."},
            "title": {"type": "string"},
            "body": {"type": "string"},
            "head": {"type": "string"},
            "base": {"type": "string"},
            "token": {"type": "string", "description": "GitHub token. Falls back to $GITHUB_TOKEN."},
        },
        "required": ["repo", "title", "body", "head", "base"],
    },
    handler=_git_create_pr,
    danger_level=DangerLevel.DESTRUCTIVE,
    tags=["git", "github"],
)


tools: list[Tool] = [
    git_status,
    git_log,
    git_diff,
    git_add,
    git_commit,
    git_push,
    git_pull,
    git_branch_create,
    git_branch_list,
    git_checkout,
    git_merge,
    git_create_pr,
]

__all__ = ["tools"]
