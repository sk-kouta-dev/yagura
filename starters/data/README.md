# yagura-starter-data

Data analysis agent. Natural-language SQL against any JDBC-style database.

## Tool surface

- **`db_query`** — Dynamic Tool. DangerAssessor Layer 2 classifies each
  query: `SELECT` → READ, `INSERT` / `UPDATE` → MODIFY, `DROP` / `DELETE`
  → DESTRUCTIVE.
- **`db_natural_query`** — Dynamic. The executor LLM translates the user's
  question into SQL, then the same Layer 2 pipeline classifies it.
- **`db_list_tables`, `db_describe_table`** — READ.
- **LLM tools** — `llm_summarize`, `llm_explain_code`, `llm_classify`,
  etc. for turning rows into narrative.
- **Snowflake** (optional) — `snowflake_query`, `snowflake_natural_query`,
  etc. when `yagura-tools-snowflake` is installed.

## Setup

```bash
pip install -r requirements.txt
python init_db.py              # writes sample_data/sample.db
export ANTHROPIC_API_KEY=sk-ant-...
python main.py
```

The sample database has three tables (`customers`, `products`, `orders`)
pre-populated with a handful of rows. The connection string is
`sqlite:///sample_data/sample.db`.

## Example session

```
You: list tables in sqlite:///sample_data/sample.db
Plan completed:
   1. [completed] List all tables → {"tables": ["customers", "products", "orders"], ...}

You: show me total revenue by customer for orders in March 2025,
     connection sqlite:///sample_data/sample.db
Plan completed:
   1. [completed] Query total revenue by customer → {"rows": [...]}

You: summarize what the data shows
Plan completed:
   1. [completed] Summarize the previous result → "Acme Corp and Umbrella ..."
```

## Customization

- **Switch to Postgres/MySQL**: install the `[postgres]` or `[mysql]`
  extra for `yagura-tools-db`, and pass `postgresql://user:pass@host/db`
  as the connection_string.
- **Switch to Snowflake**: uncomment `yagura-tools-snowflake` in
  `requirements.txt`. `tools.py` auto-detects the package.
- **Protect production DBs**: upgrade the preset from `internal_tool()`
  to `enterprise()` in `config.py`. Every SELECT, INSERT, and DROP will
  then go through explicit confirmation.
