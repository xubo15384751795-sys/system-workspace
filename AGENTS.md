# Agent Execution Guidelines for Verity

This workspace operates on a **Local-Edit, Remote-Compute** model:

1. **Code Files**: Stored and edited on the Mac local workspace (`/Users/a1/Verity`).
2. **Environment & Runtime**: Python 3.13 virtual environment and heavy workloads run on remote `ai-box` (Linux WSL2, `~/Verity`).
3. **Execution Command**:
   - To run tests or scripts, sync code and execute on `ai-box`:
     ```bash
     ./scripts/sync_to_ai_box.sh && ssh ai-box 'export PATH="$HOME/.local/bin:$PATH"; cd ~/Verity && uv run pytest'
     ```
   - Or use Makefile targets: `make remote-test`, `make sync`.
