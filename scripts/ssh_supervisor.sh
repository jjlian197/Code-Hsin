#!/bin/sh
# Finder/打包程序异常退出时也结束自身 SSH；不依赖额外 Python 安装。
parent_pid="$1"
shift
"$@" &
ssh_pid=$!
cleanup() {
  kill -TERM "$ssh_pid" 2>/dev/null || true
  wait "$ssh_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 0' TERM INT
while kill -0 "$parent_pid" 2>/dev/null && kill -0 "$ssh_pid" 2>/dev/null; do
  sleep 0.2
done
if kill -0 "$parent_pid" 2>/dev/null; then
  wait "$ssh_pid"
  exit "$?"
fi
exit 0
