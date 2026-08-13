#!/usr/bin/env bash
# Create an isolated, reproducible development environment.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${REPOPILOT_VENV:-$ROOT/.venv}"

echo "Creating RepoPilot environment at $VENV..."
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV/bin/python" -m pip install -e "$ROOT[dev,symbols]"

echo
echo "RepoPilot is installed. Try:"
echo "  $VENV/bin/repopilot --help"
echo
echo "Optional extras:"
echo "  $VENV/bin/python -m pip install -e '$ROOT[llm]'  # LLM support is dependency-free"
echo "  # To use --use-llm, copy .env.example to .env and set LLM_API_KEY"
