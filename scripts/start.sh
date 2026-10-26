#!/usr/bin/env bash
# 启动 OA LangGraph Agent（单进程 / 单 worker）。用法：
#   scripts/start.sh                 MySQL，Cookie Secure，需 HTTPS 反代
#   HOST=0.0.0.0 PORT=9000 scripts/start.sh --build
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8765}"
export OA_AGENT_DATA_DIR="${OA_AGENT_DATA_DIR:-$ROOT/data}"
BUILD=0
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=1 ;;
    *) echo "未知参数：$arg" >&2; exit 2 ;;
  esac
done

command -v uv >/dev/null || { echo "未找到 uv：请先安装 https://docs.astral.sh/uv/" >&2; exit 1; }
(cd "$ROOT/backend" && uv sync)

if [[ $BUILD == 1 || ! -f "$ROOT/frontend/dist/admin/index.html" ]]; then
  command -v npm >/dev/null || { echo "未找到 npm：请安装 Node.js 18+，或拷贝已构建的 frontend/dist" >&2; exit 1; }
  (cd "$ROOT/frontend" && npm ci && npm run build)
fi

cd "$ROOT/backend"
if [[ -f "$OA_AGENT_DATA_DIR/bootstrap.json" ]]; then
  echo "执行数据库迁移……"
  uv run alembic upgrade head
else
  echo "尚未安装：启动后访问 http://$HOST:$PORT/setup/ ，安装令牌在 $OA_AGENT_DATA_DIR/setup.token"
fi
echo "启动 Agent：http://$HOST:$PORT/  数据目录：$OA_AGENT_DATA_DIR"
exec uv run uvicorn oa_agent.main:app --host "$HOST" --port "$PORT" --workers 1 --proxy-headers
