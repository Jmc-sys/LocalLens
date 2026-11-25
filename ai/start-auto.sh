#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if ! docker compose ps --status running --services | grep -qx backend; then
  echo 'Start LocalLens backend before the AI scheduler.' >&2
  exit 1
fi
DB_PASSWORD="$(docker compose exec -T backend sh -c 'printf %s "$DB_PASSWORD"')"
if [ -z "$DB_PASSWORD" ]; then
  echo 'Backend DB_PASSWORD is empty; AI scheduler not started.' >&2
  exit 1
fi
export DB_PASSWORD
exec docker compose -f docker-compose.yml -f ai/compose.ai.yml -f ai/compose.auto.yml \
  --profile ai up -d --build ai-scheduler
