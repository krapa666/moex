#!/usr/bin/env bash
set -euo pipefail

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[compose-up] error: required command not found: $cmd" >&2
    exit 1
  fi
}

require_cmd docker

SYNC_BACKUP_DIR="./backups/mode-sync"
SYNC_BACKUP_FILE="${SYNC_BACKUP_DIR}/latest.sql.gz"

import_snapshot_into_compose_db() {
  if [[ ! -s "${SYNC_BACKUP_FILE}" ]]; then
    echo "[compose-up] no shared snapshot found, import skipped"
    return
  fi
  if ! docker compose ps db --status running >/dev/null 2>&1; then
    echo "[compose-up] db container is not running, import skipped" >&2
    return
  fi

  echo "[compose-up] importing shared snapshot from ${SYNC_BACKUP_FILE}..."
  if gunzip -c "${SYNC_BACKUP_FILE}" | docker compose exec -T db psql -v ON_ERROR_STOP=1 -U postgres -d fair_price >/dev/null; then
    echo "[compose-up] snapshot import completed"
  else
    echo "[compose-up] warning: failed to import shared snapshot" >&2
  fi
}

if command -v minikube >/dev/null 2>&1; then
  echo "[compose-up] restoring host docker context (if minikube docker-env was enabled)..."
  # shellcheck disable=SC2046
  # shellcheck disable=SC1090
  eval "$(minikube docker-env -u 2>/dev/null || true)"
fi

echo "[compose-up] starting docker compose stack..."
docker compose up -d --build "$@"
import_snapshot_into_compose_db

echo "[compose-up] done"
echo "[compose-up] frontend: http://junibox/"

if [[ -x "./scripts/configure-nginx-compose-proxy.sh" ]]; then
  echo "[compose-up] switching nginx reverse-proxy to compose mode..."
  if [[ -w "/etc/nginx/conf.d" ]]; then
    ./scripts/configure-nginx-compose-proxy.sh --reload || true
  elif command -v sudo >/dev/null 2>&1; then
    sudo ./scripts/configure-nginx-compose-proxy.sh --reload || true
  else
    echo "[compose-up] warning: no permissions to reload nginx. Run manually:" >&2
    echo "  sudo ./scripts/configure-nginx-compose-proxy.sh --reload" >&2
  fi
fi
