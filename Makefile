.PHONY: setup test lint demo api

setup:
	./scripts/setup.sh

test:
	.venv/bin/pytest

lint:
	.venv/bin/ruff check .

demo:
	./scripts/demo.sh

api:
	.venv/bin/uvicorn repopilot.api:app --host 127.0.0.1 --port 8000 --reload
