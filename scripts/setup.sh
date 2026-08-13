#!/usr/bin/env bash
# Install RepoPilot into the active Python environment (>=3.11).
# No venv required: after this, the `repopilot` command is on PATH.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Installing RepoPilot (editable, with dev tools)..."
python3 -m pip install -e "$ROOT[dev]"

echo
echo "RepoPilot is installed. Try:"
echo "  repopilot --help"
echo
echo "Optional extras:"
echo "  python3 -m pip install -e '$ROOT[symbols]'   # tree-sitter definition weighting"
echo "  python3 -m pip install -e '$ROOT[llm]'       # marks LLM support (zero extra deps)"
echo "  # To use --use-llm, copy .env.example to .env and set LLM_API_KEY"
