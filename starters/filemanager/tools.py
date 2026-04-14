"""File management tools: file/directory ops + PDF extraction + OCR."""

from __future__ import annotations

from yagura_tools.common.directory import directory_create, directory_list
from yagura_tools.common.file import (
    file_copy,
    file_delete,
    file_move,
    file_read,
    file_write,
)
from yagura_tools.scraping import tools as _scraping_tools

# Include only the read-oriented scraping tools (pdf/ocr); skip web scraping here.
_pdf_ocr = [t for t in _scraping_tools if t.name in {"pdf_extract_text", "ocr_image"}]

all_tools = [
    file_read,
    file_write,
    file_copy,
    file_move,
    file_delete,
    directory_list,
    directory_create,
    *_pdf_ocr,
]
