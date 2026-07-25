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

.PHONY: install-dev test test-verbose audit freshness dry-run status \
       work-quick work-standard work-full clean

PYTHON ?= python3

# Python path: scripts + Workbench/src + root
PYTHONPATH := Workbench/src:scripts:.

install-dev:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements-dev.txt

test:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m pytest tests -q

test-verbose:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m pytest tests -v

audit:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/commands/weekly/architecture_reality_audit.py --json

freshness:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/freshness_validator.py

dry-run:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/daily_run.py --dry-run

status:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/freshness_validator.py
	@echo "---"
	@cat Output/current/work_brief.md 2>/dev/null | head -20

work-quick:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/run_work_cycle.py --mode quick

work-standard:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/run_work_cycle.py --mode standard

work-full:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/daily_run.py --skip-harvester --skip-etf

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
