#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"

python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip setuptools wheel
EXTRAS="dev"
if [[ "${1:-}" == "--llm" ]]; then
  EXTRAS="dev,llm"
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--llm]" >&2
  exit 2
fi

"$VENV/bin/python" -m pip install -e "$ROOT[$EXTRAS]"

echo
echo "RepoPilot environment is ready."
if [[ "$EXTRAS" == "dev,llm" ]]; then
  echo "LLM support is ready (zero extra dependencies). Copy .env.example to .env and set LLM_API_KEY."
fi
echo "Run: cd $ROOT && make demo"
