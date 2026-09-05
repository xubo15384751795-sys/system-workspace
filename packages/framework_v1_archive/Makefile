# Structural Deformation Research System — Quality Gates

.PHONY: test typecheck lint check clean

PYTHON ?= python3
PYTEST := $(PYTHON) -m pytest -q
MYPY := $(PYTHON) -m mypy
RUFF := $(PYTHON) -m ruff check

test:
	$(PYTEST) tests/

typecheck:
	$(MYPY) src/core src/runtime src/data_access src/data

lint:
	$(RUFF) src/ tests/

check: test typecheck
	@echo ""
	@echo "=============================="
	@echo " All quality gates passed"
	@echo "=============================="

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name *.egg-info -exec rm -rf {} + 2>/dev/null || true
