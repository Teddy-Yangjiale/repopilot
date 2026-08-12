#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-/home/teddy/hello-agents-lab/references/hello-agents-framework}"

"$ROOT/.venv/bin/repopilot" investigate \
  --repo "$TARGET" \
  --question "How does ReActAgent execute tools and decide when to finish?" \
  --keyword ReActAgent \
  --keyword invoke_with_tools \
  --keyword Finish
