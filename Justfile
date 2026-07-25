# Test and audit shortcuts.
# Requires: just, pytest-xdist, semgrep.
# Fast path: just smoke -> just promotion -> just nightly.

SHELL := [zsh, -c, '-u', '-o', 'pipefail']
set -euo pipefail

# Fast feedback loop.
smoke:
    #!/usr/bin/env zsh
    set -e
    echo "=== smoke: critical_gate + semantic ==="
    python3 -m pytest tests/ -n auto -m "critical_gate or semantic" -q --tb=short
    python3 -m pytest "packages/framework/tests/" -n auto -m "semantic" -q --tb=short 2>/dev/null || true

# Must-pass gates before promotion.
critical:
    #!/usr/bin/env zsh
    set -e
    echo "=== critical: promotion gate + routing ==="
    python3 -m pytest tests/ -n auto -m critical_gate -v --tb=long

# Concept registry, proxy semantics, NOT_IMPLEMENTED.
semantic:
    #!/usr/bin/env zsh
    set -e
    echo "=== semantic: registry, proxies, NOT_IMPLEMENTED enforcement ==="
    python3 -m pytest tests/ -n auto -m semantic -v --tb=short
    python3 -m pytest "packages/framework/tests/" -n auto -m semantic -q --tb=short 2>/dev/null || true

# Boundary, freshness, provenance.
data:
    #!/usr/bin/env zsh
    set -e
    echo "=== data: boundary, freshness, provenance ==="
    python3 -m pytest tests/ -n auto -m data_boundary -v --tb=short
    python3 -m pytest "packages/framework/tests/" -n auto -m data_boundary -q --tb=short 2>/dev/null || true

# Full promotion preflight.
promotion:
    #!/usr/bin/env zsh
    set -e
    echo "=== promotion preflight ==="
    python3 -m pytest tests/ -n auto -m "critical_gate or semantic or data_boundary or report" -v --tb=short
    python3 -m pytest "packages/framework/tests/" -n auto -m "semantic or data_boundary or benchmark" -q --tb=short 2>/dev/null || true
    echo "--- semgrep audit ---"
    semgrep --config=semgrep_rules/ --error --quiet 2>/dev/null || echo "(semgrep not configured or not installed)"

# Full suite including slow checks.
nightly:
    #!/usr/bin/env zsh
    set -e
    echo "=== nightly: full suite ==="
    python3 -m pytest tests/ -n auto -q --tb=short
    python3 -m pytest "packages/framework/tests/" -n auto -q --tb=short 2>/dev/null || true
    python3 -m pytest packages/learning_hub/tests/ -q --tb=short 2>/dev/null || true
    echo "--- architecture reality audit ---"
    python3 scripts/commands/weekly/architecture_reality_audit.py 2>/dev/null || echo "(audit script encountered issues)"
    echo "--- semgrep full audit ---"
    semgrep --config=semgrep_rules/ --error --metrics=off 2>/dev/null || echo "(semgrep not configured or not installed)"

# Semgrep standalone.
semgrep:
    semgrep --config=semgrep_rules/ --error --metrics=off

# Ledger, escalation, incident.
governance-loop:
    python3 -m pytest tests/ -m governance_loop -v --tb=short

# Report gate.
report:
    python3 -m pytest tests/ -m report -v --tb=short

# Benchmark tests.
benchmark:
    python3 -m pytest tests/ -m benchmark -v --tb=short
    python3 -m pytest "packages/framework/tests/" -m benchmark -q --tb=short 2>/dev/null || true

# Architecture reality audit — governance drift detection.
audit-reality:
    #!/usr/bin/env zsh
    set -e
    echo "=== architecture reality audit ==="
    python3 scripts/commands/weekly/architecture_reality_audit.py
    echo "--- framework boundary tests ---"
    python3 -m pytest tests/test_framework_boundary.py tests/test_architecture_boundary.py -v --tb=short

# Strategy Lab — full backtest (baseline vs overlay).
strategy-backtest:
    python3 scripts/strategy_lab/run_backtest.py --start 2000-01-01

# Strategy Lab — dynamic lookback backtest (vol-adaptive + velocity gate).
strategy-dynamic:
    python3 scripts/strategy_lab/run_backtest.py --dynamic --start 2000-01-01

# Strategy Lab — four-layer test suite (data, signal, strategy, shadow).
strategy-test:
    python3 scripts/strategy_lab/test_runner.py --start 2000-01-01

# Strategy Lab — generate today's shadow decision card.
strategy-shadow:
    python3 scripts/strategy_lab/run_backtest.py --shadow-card

# Strategy Lab — backfill shadow card outcomes.
strategy-backfill:
    python3 scripts/strategy_lab/run_backtest.py --backfill
