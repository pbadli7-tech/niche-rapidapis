#!/usr/bin/env bash
# Run all 5 APIs locally in parallel for development.
# Usage: bash run_local.sh
# Logs: each API writes to logs/<name>.log

set -e
ROOT=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$ROOT/logs"

export PYTHONPATH="$ROOT"

kill_all() {
  echo "Stopping all APIs..."
  kill $(jobs -p) 2>/dev/null || true
}
trap kill_all EXIT INT TERM

run_api() {
  local name=$1
  local port=$2
  local dir="$ROOT/$name"
  echo "Starting $name on :$port"
  cd "$dir"
  uvicorn main:app --host 0.0.0.0 --port "$port" --reload \
    > "$ROOT/logs/$name.log" 2>&1 &
}

run_api crypto-intelligence-api  8001
run_api pincode-api               8002
run_api food-intelligence-api     8003
run_api news-sentiment-api        8004
run_api cricket-stats-api         8005

echo ""
echo "All APIs started:"
echo "  Crypto Intelligence  → http://localhost:8001/docs"
echo "  Indian Pincode       → http://localhost:8002/docs"
echo "  Food Intelligence    → http://localhost:8003/docs"
echo "  News Sentiment       → http://localhost:8004/docs"
echo "  Cricket Fantasy      → http://localhost:8005/docs"
echo ""
echo "Press Ctrl+C to stop all."
wait
