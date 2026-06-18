# Makefile — lightweight dev commands for the Structural Deformation System.
#
# Usage:
#   make install-dev    Install development dependencies
#   make test           Run root test suite
#   make audit          Run architecture boundary audit
#   make freshness      Run freshness validator
#   make dry-run        Daily pipeline dry-run (no data fetching)
#   make status         Show system status
#   make work-quick     Quick reaction run (skip harvester + ETF)

.PHONY: install-dev test audit freshness dry-run status work-quick clean

# Python path: scripts + Workbench/src + root
PYTHONPATH := Workbench/src:scripts:.

install-dev:
	pip install --upgrade pip
	pip install pyyaml jsonschema pandas numpy scikit-learn hmmlearn pytest

test:
	PYTHONPATH=$(PYTHONPATH) python -m pytest tests -q

test-verbose:
	PYTHONPATH=$(PYTHONPATH) python -m pytest tests -v

audit:
	PYTHONPATH=$(PYTHONPATH) python scripts/architecture_reality_audit.py --json

freshness:
	PYTHONPATH=$(PYTHONPATH) python scripts/freshness_validator.py

dry-run:
	PYTHONPATH=$(PYTHONPATH) python scripts/daily_run.py --dry-run

status:
	PYTHONPATH=$(PYTHONPATH) python scripts/freshness_validator.py
	@echo "---"
	@cat Output/current/work_brief.md 2>/dev/null | head -20

work-quick:
	PYTHONPATH=$(PYTHONPATH) python scripts/daily_run.py --skip-harvester --skip-etf

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
