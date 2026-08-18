# Makefile — lightweight dev commands for the Structural Deformation System.
#
# Usage:
#   make install-dev    Install development dependencies
#   make test           Run root test suite
#   make audit          Run architecture boundary audit
#   make freshness      Run freshness validator
#   make dry-run        Daily pipeline dry-run (no data fetching)
#   make status         Show system status
#   make work-quick     Quick reaction run (read-only, no pipeline)
#   make work-standard  Standard work cycle (re-judge, no data fetch)
#   make work-full      Full daily pipeline

.PHONY: install-dev test test-operator test-verbose audit freshness dry-run status \
       work-quick work-standard work-full clean

UV ?= uv
UV_RUN := $(UV) run --locked

install-dev:
	$(UV) sync --locked --all-packages

test:
	$(UV_RUN) python -m pytest tests -q

test-operator:
	$(UV_RUN) python scripts/run_operator_tests.py --allow-operator-workspace

test-verbose:
	$(UV_RUN) python -m pytest tests -v

audit:
	$(UV_RUN) python scripts/commands/weekly/architecture_reality_audit.py --json

freshness:
	$(UV_RUN) python scripts/freshness_validator.py

dry-run:
	$(UV_RUN) python scripts/daily_run.py --dry-run

status:
	$(UV_RUN) python scripts/freshness_validator.py
	@echo "---"
	@cat Output/current/work_brief.md 2>/dev/null | head -20

work-quick:
	$(UV_RUN) python scripts/run_work_cycle.py --mode quick

work-standard:
	$(UV_RUN) python scripts/run_work_cycle.py --mode standard

work-full:
	$(UV_RUN) python scripts/daily_run.py --skip-harvester --skip-etf

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
