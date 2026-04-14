# yagura-starter-filemanager

File organization agent. Inspired by Shelfy-style file assistants.

## What it does

- Searches, reads, copies, moves, and (with confirmation) deletes files.
- Extracts text from PDFs.
- OCRs image files (optional — install the `[ocr]` extra).
- Preset: `internal_tool` — READ auto-executes, everything else confirms,
  full audit log at `./filemanager_audit.jsonl`.

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python main.py
```

To enable OCR, install Tesseract on your system and uncomment the `[ocr]`
line in `requirements.txt`.

## Tool inventory

| Tool | DangerLevel |
|---|---|
| `file_read`, `directory_list` | READ |
| `file_write`, `file_copy`, `file_move`, `directory_create` | MODIFY |
| `file_delete` | DESTRUCTIVE (always confirms) |
| `pdf_extract_text` | READ |
| `ocr_image` | READ (optional) |

## Extending

- **Bulk operations**: ask the agent things like "move all PDFs older than
  90 days in ~/Downloads to /tmp/archive" — the planner will chain
  `directory_list` → `file_move` across matching entries.
- **Add cloud backends**: `pip install yagura-tools-aws` and append
  `yagura_tools.aws.tools` to `all_tools` for S3-backed file ops.
- **Tighter safety**: change `safety_presets.internal_tool()` to
  `safety_presets.enterprise()` in `config.py` to require confirmation
  on every plan.
