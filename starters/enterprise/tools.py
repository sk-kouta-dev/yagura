"""Office + DB tool bundle for the enterprise template."""

from __future__ import annotations

from yagura_tools.common.directory import directory_list
from yagura_tools.common.file import file_read
from yagura_tools.db import tools as _db_tools
from yagura_tools.google import tools as _google_tools
from yagura_tools.slack import tools as _slack_tools

all_tools = [
    # Read-only local FS for debugging/auditing.
    file_read,
    directory_list,
    *_google_tools,
    *_slack_tools,
    *_db_tools,
]
