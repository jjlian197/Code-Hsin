#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [[ "$(uname -s)" != Darwin ]]; then
  echo "此构建脚本仅用于 macOS。" >&2
  exit 1
fi
if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  "$PROJECT_DIR/scripts/setup_macos.sh"
fi
cd "$PROJECT_DIR"
"$PROJECT_DIR/.venv/bin/python" -m pip install -r requirements-build-macos.txt
"$PROJECT_DIR/.venv/bin/python" -m PyInstaller --noconfirm packaging/Hsin-macos.spec
echo "开发包已生成：$PROJECT_DIR/dist/Hsin.app"
