#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-/path/to/your/repo}"

repopilot investigate \
  --repo "$TARGET" \
  --question "How does ReActAgent execute tools and decide when to finish?" \
  --keyword ReActAgent \
  --keyword invoke_with_tools \
  --keyword Finish
