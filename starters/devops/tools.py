"""DevOps tool bundle: Docker + Kubernetes + Git + common."""

from __future__ import annotations

from yagura_tools.common.directory import directory_list
from yagura_tools.common.file import file_read
from yagura_tools.common.shell import shell_execute
from yagura_tools.docker import tools as _docker_tools
from yagura_tools.git import tools as _git_tools
from yagura_tools.k8s import tools as _k8s_tools

all_tools = [
    # Minimal common surface — we're already giving the agent Docker + K8s + Git,
    # so keep extra local FS access tight.
    shell_execute,
    file_read,
    directory_list,
    *_docker_tools,
    *_k8s_tools,
    *_git_tools,
]
