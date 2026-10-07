#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  echo "尚未安装运行环境，请先运行 scripts/setup_macos.sh。" >&2
  exit 1
fi
# Finder may inherit unrelated Python settings; use this project's environment.
unset PYTHONHOME PYTHONPATH
exec "$PROJECT_DIR/.venv/bin/python" -m src.main "$@"
