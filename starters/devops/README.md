# yagura-starter-devops

DevOps automation agent. Natural-language control over containers,
Kubernetes resources, and git workflows.

## Safety profile

Preset: `enterprise` (SERVER environment).

- **Every plan requires explicit confirmation** — no auto-execution.
- `write_file` escalates from MODIFY → DESTRUCTIVE (production write
  discipline).
- Audit log at `./devops_audit.jsonl` (override via `audit_path` arg).
- API-key auth supported via `$YAGURA_API_KEYS=key1=alice,key2=bob`.
- Up to 5 concurrent user sessions (override in `config.py`).

## Prerequisites

- **Docker**: a reachable Docker daemon (tools-docker uses the SDK).
- **Kubernetes**: a valid `~/.kube/config` or in-cluster service account.
- **Git**: a local repository for `git_*` tools to operate on.
- **GitHub PR creation** (optional): `pip install yagura-tools-git[github]`
  and set `GITHUB_TOKEN` for `git_create_pr`.

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python main.py
```

## Example workflows

- "Show pods in the `staging` namespace filtered by `app=api`"
- "Roll back the `checkout` deployment to the previous revision"
- "Push the current branch as `feat/onboarding` and open a PR into `main`"
- "Build a Docker image from `./backend` tagged `acme/api:v2` and list
  running containers afterward"

## Customization

- **Tighten scope**: remove `shell_execute` from `tools.py` — shell is a
  very broad capability and Layer 2 LLM assessment may not always catch
  edge cases.
- **Allow read auto-execute**: overlay `{"auto_execute_threshold":
  DangerLevel.READ}` on top of the enterprise preset in `config.py`.
- **Push to monitoring**: swap the file logger for
  `yagura-logger-datadog` or `yagura-logger-cloudwatch`.
