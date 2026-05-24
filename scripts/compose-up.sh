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

COMPOSE_PROJECT="${MOEX_COMPOSE_PROJECT:-moex}"
BACKEND_BIND="${MOEX_BACKEND_BIND:-0.0.0.0}"
BACKEND_PORT="${MOEX_BACKEND_PORT:-18000}"
FRONTEND_BIND="${MOEX_FRONTEND_BIND:-0.0.0.0}"
FRONTEND_PORT="${MOEX_FRONTEND_PORT:-8080}"
OBSERVABILITY_BIND="${MOEX_OBSERVABILITY_BIND:-127.0.0.1}"
PROMETHEUS_PORT="${MOEX_PROMETHEUS_PORT:-9090}"
GRAFANA_PORT="${MOEX_GRAFANA_PORT:-3000}"
LOKI_PORT="${MOEX_LOKI_PORT:-3100}"

STEP=0
log_step() {
  STEP=$((STEP + 1))
  echo "[compose-up][step ${STEP}] $1"
}

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
  log_step "restoring host docker context (if minikube docker-env was enabled)"
  # shellcheck disable=SC2046
  # shellcheck disable=SC1090
  eval "$(minikube docker-env -u 2>/dev/null || true)"
fi

log_step "starting docker compose stack"
docker compose up -d --build "$@"
log_step "importing shared DB snapshot (if present)"
import_snapshot_into_compose_db

log_step "compose mode is up"
echo "[compose-up] compose project: ${COMPOSE_PROJECT}"
echo "[compose-up] frontend (internet + LAN): http://${FRONTEND_BIND}:${FRONTEND_PORT}/"
echo "[compose-up] backend API (direct host access): http://${BACKEND_BIND}:${BACKEND_PORT}/"
echo "[compose-up] prometheus (local-only by default): http://${OBSERVABILITY_BIND}:${PROMETHEUS_PORT}/prometheus/"
echo "[compose-up] grafana (local-only by default): http://${OBSERVABILITY_BIND}:${GRAFANA_PORT}/grafana/"
echo "[compose-up] loki (local-only by default): http://${OBSERVABILITY_BIND}:${LOKI_PORT}/loki/"

if [[ -x "./scripts/configure-nginx-compose-proxy.sh" ]]; then
  log_step "switching nginx reverse-proxy to compose mode"
  if [[ -w "/etc/nginx/conf.d" ]]; then
    ./scripts/configure-nginx-compose-proxy.sh --reload || true
  elif command -v sudo >/dev/null 2>&1; then
    sudo ./scripts/configure-nginx-compose-proxy.sh --reload || true
  else
    echo "[compose-up] warning: no permissions to reload nginx. Run manually:" >&2
    echo "  sudo ./scripts/configure-nginx-compose-proxy.sh --reload" >&2
  fi
fi
