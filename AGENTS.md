# Agent Execution Guidelines for Verity

Default execution is **local** on this Mac (`/Users/a1/Verity`).

1. **Edit and run here**: tests, scripts, dry-runs, and pipelines use the local Python 3.13 environment (`.venv`, `uv run`, or `make test`).
2. **Do not sync or SSH to `ai-box` unless the operator explicitly asks.**
3. Remote compute stays deferred until the local daily path is stable and running. `./scripts/sync_to_ai_box.sh` remains an opt-in path for that later stage.
