#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [[ "$(uname -s)" != Darwin ]]; then
  echo "此安装脚本仅用于 macOS。" >&2
  exit 1
fi
PYTHON_BIN="${HSIN_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  for candidate in /opt/homebrew/bin/python3.11 /usr/local/bin/python3.11; do
    if [[ -x "$candidate" ]]; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "请先安装 Python 3.11，或用 HSIN_PYTHON 指定其绝对路径。" >&2
  exit 1
fi
if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  "$PYTHON_BIN" -m venv "$PROJECT_DIR/.venv"
fi
"$PROJECT_DIR/.venv/bin/python" -m pip install -r "$PROJECT_DIR/requirements-macos.txt"
echo "环境准备完成。配置双形态模型后，双击 启动心.command。"
