"""Data tool bundle: DB + Snowflake + LLM + minimal common."""

from __future__ import annotations

from yagura_tools.common.file import file_read, file_write
from yagura_tools.db import tools as _db_tools
from yagura_tools.llm import tools as _llm_tools

# Snowflake is optional — pull it in only when the package is installed.
try:
    from yagura_tools.snowflake import tools as _snowflake_tools
except ImportError:
    _snowflake_tools = []

all_tools = [
    # Local output files (csv, markdown reports).
    file_read,
    file_write,
    *_db_tools,
    *_snowflake_tools,
    *_llm_tools,
]
