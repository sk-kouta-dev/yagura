# yagura-starter-office

Office-automation agent for Google Workspace and Slack.

## Tool surface

| Group | Tools |
|---|---|
| Gmail | `gmail_send` (DESTRUCTIVE), `gmail_search`, `gmail_read`, `gmail_draft_create` |
| Drive | `gdrive_search`, `gdrive_download`, `gdrive_upload`, `gdrive_move`, `gdrive_delete` (DESTRUCTIVE) |
| Calendar | `gcalendar_list`, `gcalendar_create`, `gcalendar_update`, `gcalendar_delete` (DESTRUCTIVE) |
| Sheets | `gsheets_read`, `gsheets_write` |
| Slack | `slack_send` (DESTRUCTIVE), `slack_search`, `slack_channel_list`, `slack_file_upload`, … |
| Local FS | `file_read`, `file_write`, `directory_list` (for attachments) |

Preset: `internal_tool` — reads auto-execute; every write/send confirms.

## Setup

1. Create a Google Cloud service account with
   Gmail, Drive, Calendar, and Sheets API access enabled, download the
   JSON key, and drop it under `credentials/service-account.json`.
2. Create a Slack app with at least `chat:write`, `channels:read`,
   `search:read`, `files:write` scopes and grab the bot token.
3. Install and run:

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export GOOGLE_APPLICATION_CREDENTIALS=./credentials/service-account.json
export SLACK_BOT_TOKEN=xoxb-...
python main.py
```

The `credentials/` directory is gitignored by default (see `.gitignore`).

## Example prompts

- "Find emails from legal about the vendor contract this week"
- "Draft an email to design@example.com summarizing yesterday's Slack
  discussion in #product"
- "Upload the attached quarterly_report.xlsx to the /Reports folder in
  Drive and post the link in #exec"
- "Create a 30-minute meeting with alice@ tomorrow 2pm called 'Roadmap
  sync'"

## Customization

- **OAuth2 per-user**: replace the service account with per-user
  `google-auth-oauthlib` flow by writing a thin credential helper in
  `config.py`.
- **Add Microsoft 365**: `pip install yagura-tools-microsoft` and union
  its `tools` into `all_tools` — you then have both Workspace and M365
  in the same agent.
- **Route to Datadog**: replace `internal_tool()`'s file logger with
  `DatadogLogger(api_key=..., service="office-agent")`.
