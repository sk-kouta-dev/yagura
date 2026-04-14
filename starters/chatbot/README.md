# yagura-starter-chatbot

Basic conversational agent with a CLI interface. Good starting point for
learning Yagura, prototyping, or building a personal assistant.

## What it does

- Accepts natural-language prompts in a terminal loop.
- Plans the response using `claude-sonnet-4-20250514`.
- Executes through 5 safe common tools:
  `shell_execute`, `file_read`, `file_write`, `directory_list`, `http_request`.
- Uses the `development` safety preset: READ and MODIFY auto-execute; DESTRUCTIVE
  (delete, send, etc.) requires a confirmation prompt.

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python main.py
```

## Customization points

- **Swap the LLM**: in `config.py`, replace `AnthropicProvider` with
  `OpenAIProvider` or `OllamaProvider`.
- **Add tools**: append to `all_tools` in `tools.py` — e.g.
  `from yagura_tools.git import tools as git_tools; all_tools += git_tools`.
- **Tighten safety**: change `safety_presets.development()` to
  `safety_presets.internal_tool()` in `config.py` — MODIFY operations
  will then also require confirmation.
- **Custom system prompt**: pass `system=...` into `Planner.generate` by
  subclassing `Planner` or by building a custom Agent wrapper.

## Example session

```
You: list the files in /tmp
Plan completed:
   1. [completed] List files in /tmp → {"entries": [...], "count": 23}

You: what's in /tmp/notes.txt?
Plan completed:
   1. [completed] Read the file /tmp/notes.txt → "shopping list\n- bread\n..."
```
