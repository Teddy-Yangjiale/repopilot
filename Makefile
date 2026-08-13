.PHONY: setup test lint demo api

setup:
	python3 -m pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check .

demo:
	./scripts/demo.sh

api:
	uvicorn repopilot.api:app --host 127.0.0.1 --port 8000 --reload
