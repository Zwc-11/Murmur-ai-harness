# Small command shortcuts for local development.
# These targets wrap the exact Python commands we expect contributors to run.
PYTHON ?= python

.PHONY: install test lint format demo replay run trace gate langsmith

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check chorus tests

format:
	$(PYTHON) -m ruff format chorus tests

demo:
	chorus demo --n 3 --event-log .chorus/demo.jsonl

replay:
	chorus replay --event-log .chorus/demo.jsonl

run:
	chorus run --n 30 --success-rate 0.7 --error-rate 0.1 --seed 7

trace:
	chorus trace --n 30 --seed 7 --replay

gate:
	chorus gate --branch main --n 20 --update-baseline
	chorus gate --branch main --n 20 --scaffold worse --success-delta -0.12 --error-rate 0.12

# Needs the [otel] extra + LANGSMITH_API_KEY. See docs/LANGSMITH_MCP_LOOP.md.
langsmith:
	chorus trace --n 12 --seed 7 --otlp --backend langsmith --project chorus
