#!/usr/bin/env bash
set -euo pipefail

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[compose-down] error: required command not found: $cmd" >&2
    exit 1
  fi
}

require_cmd docker

SYNC_BACKUP_DIR="./backups/mode-sync"
SYNC_BACKUP_FILE="${SYNC_BACKUP_DIR}/latest.sql.gz"

export_compose_db_snapshot() {
  if ! docker compose ps db --status running >/dev/null 2>&1; then
    echo "[compose-down] db container is not running, skipping snapshot export"
    return
  fi

  mkdir -p "${SYNC_BACKUP_DIR}"
  echo "[compose-down] exporting DB snapshot to ${SYNC_BACKUP_FILE}..."
  if docker compose exec -T db pg_dump --clean --if-exists --no-owner --no-privileges -U postgres -d fair_price | gzip -c > "${SYNC_BACKUP_FILE}.tmp"; then
    mv "${SYNC_BACKUP_FILE}.tmp" "${SYNC_BACKUP_FILE}"
    echo "source=compose generated_at=$(date -Iseconds)" > "${SYNC_BACKUP_DIR}/latest.meta"
    echo "[compose-down] snapshot export completed"
  else
    rm -f "${SYNC_BACKUP_FILE}.tmp"
    echo "[compose-down] warning: failed to export DB snapshot" >&2
  fi
}

if command -v minikube >/dev/null 2>&1; then
  echo "[compose-down] restoring host docker context (if minikube docker-env was enabled)..."
  # shellcheck disable=SC2046
  # shellcheck disable=SC1090
  eval "$(minikube docker-env -u 2>/dev/null || true)"
fi

echo "[compose-down] stopping docker compose stack..."
export_compose_db_snapshot
docker compose down "$@"

echo "[compose-down] done"
