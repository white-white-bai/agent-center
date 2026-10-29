#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ "${1:-}" == "--stop" ]]; then
  echo "Stopping Agent Center..."
  docker compose down
  exit 0
fi

if [[ "${1:-}" == "--logs" ]]; then
  docker compose logs -f app
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Install Docker first." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker engine is not running. Starting it if possible..."
  if [[ "$(uname -s)" == "Darwin" ]]; then
    open -a Docker || true
  else
    sudo systemctl start docker || true
  fi
  for _ in $(seq 1 30); do
    sleep 5
    if docker info >/dev/null 2>&1; then break; fi
  done
  if ! docker info >/dev/null 2>&1; then
    echo "Docker engine did not become ready in time." >&2
    exit 1
  fi
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example. Fill AC_LLM_API_KEY to use a real model."
fi

echo "Building and starting containers..."
docker compose up -d --build

echo "Waiting for http://127.0.0.1:8000/healthz ..."
ready=0
for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 3
done

if [[ "$ready" -ne 1 ]]; then
  echo "Application did not become healthy. Recent logs:" >&2
  docker compose logs --tail 80 app
  exit 1
fi

cat <<'EOF'

Agent Center is running.
  API docs : http://localhost:8000/docs
  Health   : http://localhost:8000/healthz
  MySQL    : localhost:3307 (agent / agent_pass, db agent_center)
  Redis    : localhost:6380
  Vector   : embedded Milvus Lite (volume milvus_lite_data)

Useful commands:
  docker compose ps
  ./scripts/start.sh --logs
  ./scripts/start.sh --stop
EOF
