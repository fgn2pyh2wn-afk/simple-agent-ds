#!/usr/bin/env bash
# 启动脚本：优先用同目录自带的虚拟环境，其次找系统里已装 openai 的 Python，最后自动安装。
set -euo pipefail
cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ] && .venv/bin/python -c "import openai" >/dev/null 2>&1; then
  exec .venv/bin/python agent.py "$@"
fi

PY="$(command -v python3 || true)"
if [ -n "$PY" ] && "$PY" -c "import openai" >/dev/null 2>&1; then
  exec "$PY" agent.py "$@"
fi

echo "没找到装了 openai 的 Python，正在创建虚拟环境并安装…"
"$PY" -m venv .venv
.venv/bin/pip install -q "openai>=1.0"
exec .venv/bin/python agent.py "$@"
