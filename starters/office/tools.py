"""Office tool bundle: Google Workspace + Slack + minimal common tools."""

from __future__ import annotations

from yagura_tools.common.directory import directory_list
from yagura_tools.common.file import file_read, file_write
from yagura_tools.google import tools as _google_tools
from yagura_tools.slack import tools as _slack_tools

all_tools = [
    # Limited local FS — enough to attach/save files, nothing destructive.
    file_read,
    file_write,
    directory_list,
    *_google_tools,
    *_slack_tools,
]
