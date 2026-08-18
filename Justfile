# Test and audit shortcuts.
# Requires: just, pytest-xdist, semgrep.
# Fast path: just smoke -> just promotion -> just nightly.

SHELL := [zsh, -c, '-u', '-o', 'pipefail']
set -euo pipefail

# All project commands use the locked Python 3.13 environment.
PY := "uv run --locked python"

# Fast feedback loop.
smoke:
    #!/usr/bin/env zsh
    set -e
    echo "=== smoke: critical_gate + semantic ==="
    {{PY}} -m pytest tests/ -n auto -m "critical_gate or semantic" -q --tb=short
    {{PY}} -m pytest "packages/framework/tests/" -n auto -m "semantic" -q --tb=short

# Must-pass gates before promotion.
critical:
    #!/usr/bin/env zsh
    set -e
    echo "=== critical: promotion gate + routing ==="
    {{PY}} -m pytest tests/ -n auto -m critical_gate -v --tb=long

# Concept registry, proxy semantics, NOT_IMPLEMENTED.
semantic:
    #!/usr/bin/env zsh
    set -e
    echo "=== semantic: registry, proxies, NOT_IMPLEMENTED enforcement ==="
    {{PY}} -m pytest tests/ -n auto -m semantic -v --tb=short
    {{PY}} -m pytest "packages/framework/tests/" -n auto -m semantic -q --tb=short

# Boundary, freshness, provenance.
data:
    #!/usr/bin/env zsh
    set -e
    echo "=== data: boundary, freshness, provenance ==="
    {{PY}} -m pytest tests/ -n auto -m data_boundary -v --tb=short
    {{PY}} -m pytest "packages/framework/tests/" -n auto -m data_boundary -q --tb=short

# Full promotion preflight.
promotion:
    #!/usr/bin/env zsh
    set -e
    echo "=== promotion preflight ==="
    {{PY}} -m pytest tests/ -n auto -m "critical_gate or semantic or data_boundary or report" -v --tb=short
    {{PY}} -m pytest "packages/framework/tests/" -n auto -m "semantic or data_boundary or benchmark" -q --tb=short
    echo "--- semgrep audit ---"
    semgrep --config=semgrep_rules/ --error --quiet

# Full suite including slow checks.
nightly:
    #!/usr/bin/env zsh
    set -e
    echo "=== nightly: full suite ==="
    {{PY}} -m pytest tests/ -n auto -q --tb=short
    {{PY}} -m pytest "packages/framework/tests/" -n auto -q --tb=short
    {{PY}} -m pytest packages/learning_hub/tests/ -q --tb=short
    echo "--- architecture reality audit ---"
    {{PY}} scripts/commands/weekly/architecture_reality_audit.py
    echo "--- semgrep full audit ---"
    semgrep --config=semgrep_rules/ --error --metrics=off

# Semgrep standalone.
semgrep:
    semgrep --config=semgrep_rules/ --error --metrics=off

# Ledger, escalation, incident.
governance-loop:
    {{PY}} -m pytest tests/ -m governance_loop -v --tb=short

# Report gate.
report:
    {{PY}} -m pytest tests/ -m report -v --tb=short

# Benchmark tests.
benchmark:
    {{PY}} -m pytest tests/ -m benchmark -v --tb=short
    {{PY}} -m pytest "packages/framework/tests/" -m benchmark -q --tb=short

# Architecture reality audit — governance drift detection.
audit-reality:
    #!/usr/bin/env zsh
    set -e
    echo "=== architecture reality audit ==="
    {{PY}} scripts/commands/weekly/architecture_reality_audit.py
    echo "--- framework boundary tests ---"
    {{PY}} -m pytest tests/test_framework_boundary.py tests/test_architecture_boundary.py -v --tb=short

# Strategy Lab — full backtest (baseline vs overlay).
strategy-backtest:
    {{PY}} scripts/strategy_lab/run_backtest.py --start 2000-01-01

# Strategy Lab — dynamic lookback backtest (vol-adaptive + velocity gate).
strategy-dynamic:
    {{PY}} scripts/strategy_lab/run_backtest.py --dynamic --start 2000-01-01

# Strategy Lab — four-layer test suite (data, signal, strategy, shadow).
strategy-test:
    {{PY}} scripts/strategy_lab/test_runner.py --start 2000-01-01

# Strategy Lab — generate today's shadow decision card.
strategy-shadow:
    {{PY}} scripts/strategy_lab/run_backtest.py --shadow-card

# Strategy Lab — backfill shadow card outcomes.
strategy-backfill:
    {{PY}} scripts/strategy_lab/run_backtest.py --backfill
