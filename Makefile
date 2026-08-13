VENV ?= .venv
PYTHON := $(VENV)/bin/python

.PHONY: setup test lint demo api

setup:
	./scripts/setup.sh

test:
	$(PYTHON) -m pytest

lint:
	$(VENV)/bin/ruff check src tests

demo:
	./scripts/demo.sh

api:
	$(VENV)/bin/uvicorn repopilot.api:app --host 127.0.0.1 --port 8000 --reload
