"""Tools registered with the chatbot.

Pulls five common tools from yagura-tools-common. Extend by appending to
`all_tools` or by importing additional ecosystem packages.
"""

from __future__ import annotations

from yagura_tools.common.directory import directory_list
from yagura_tools.common.file import file_read, file_write
from yagura_tools.common.http import http_request
from yagura_tools.common.shell import shell_execute

all_tools = [
    shell_execute,
    file_read,
    file_write,
    directory_list,
    http_request,
]
