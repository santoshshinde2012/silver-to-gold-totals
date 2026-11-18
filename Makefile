# Common tasks. `make` alone runs the full check, the same as ./run_demo.sh plus lint and types.
.PHONY: all setup test lint types demo report snapshot clean

VENV := .venv
PY := $(VENV)/bin/python

all: lint types test demo

$(VENV):
	python3 -m venv $(VENV)

setup: $(VENV)
	$(PY) -m pip install -q -r requirements.txt ruff mypy

test: setup
	$(PY) -m pytest

lint: setup
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

types: setup
	$(PY) -m mypy src

demo: setup
	$(PY) -m src.totals_demo

report: setup
	$(PY) -m src.inspection --lake lake --output docs/results

snapshot: report
	$(PY) scripts/capture_snapshot.py

clean:
	rm -rf $(VENV) lake .pytest_cache .ruff_cache .mypy_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
