#!/usr/bin/env bash
# Start an AI batch using the *running backend's* DB password, without printing it.
# Usage: bash ai/run-scan.sh --limit 25 [--user-id N] [--pause 1]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Do not start a second simultaneous scan of the same library.
if docker ps --filter 'label=com.docker.compose.service=ai-indexer' --filter status=running \
    --format '{{.ID}}' | grep -q .; then
  echo 'An AI indexer is already running. Check the AI panel for progress.' >&2
  exit 1
fi

if ! docker compose ps --status running --services | grep -qx backend; then
  echo 'LocalLens backend is not running. Start the backend first.' >&2
  exit 1
fi
# The backend already has a working DB_PASSWORD in its container environment.
# Capture it into a transient, exported variable for this Compose invocation.
DB_PASSWORD="$(docker compose exec -T backend sh -c 'printf %s "$DB_PASSWORD"')"
if [ -z "$DB_PASSWORD" ]; then
  echo 'Backend DB_PASSWORD is missing; no AI scan started.' >&2
  exit 1
fi
export DB_PASSWORD
# This must be run AFTER the ai_scan_jobs.sql migration has been applied.
exec docker compose -f docker-compose.yml -f ai/compose.ai.yml \
  run --rm ai-indexer python /opt/ai/scan.py "$@"
