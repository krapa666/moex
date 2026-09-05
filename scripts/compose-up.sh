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
RESTORE_SYNC_SNAPSHOT="${MOEX_RESTORE_SYNC_SNAPSHOT:-auto}"
PUBLIC_DOMAIN="${MOEX_PUBLIC_DOMAIN:-${MOEX_SERVER_NAME:-moex.junnylab.ru}}"
SERVER_NAMES="${MOEX_NGINX_SERVER_NAMES:-${PUBLIC_DOMAIN}}"
SSL_CERT_PATH="${MOEX_SSL_CERT_PATH:-/etc/letsencrypt/live/${PUBLIC_DOMAIN}/fullchain.pem}"
SSL_CERT_KEY_PATH="${MOEX_SSL_CERT_KEY_PATH:-/etc/letsencrypt/live/${PUBLIC_DOMAIN}/privkey.pem}"
FORCE_HTTPS="${MOEX_FORCE_HTTPS:-}"

COMPOSE_PROJECT="${MOEX_COMPOSE_PROJECT:-moex}"
BACKEND_BIND="${MOEX_BACKEND_BIND:-127.0.0.1}"
BACKEND_PORT="${MOEX_BACKEND_PORT:-18000}"
FRONTEND_BIND="${MOEX_FRONTEND_BIND:-127.0.0.1}"
FRONTEND_PORT="${MOEX_FRONTEND_PORT:-8080}"

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

  local relation=""
  local row_count="0"
  relation="$(docker compose exec -T db psql -Atq -U postgres -d fair_price -c "SELECT to_regclass('public.analyst_tables')" 2>/dev/null || true)"
  if [[ -n "${relation}" ]]; then
    row_count="$(docker compose exec -T db psql -Atq -U postgres -d fair_price -c "SELECT COUNT(*) FROM analyst_tables" 2>/dev/null || echo 0)"
  fi

  if [[ "${RESTORE_SYNC_SNAPSHOT}" == "auto" && "${row_count:-0}" -gt 0 ]]; then
    echo "[compose-up] existing application data found; automatic snapshot restore skipped"
    echo "[compose-up] set MOEX_RESTORE_SYNC_SNAPSHOT=force only when an intentional restore is required"
    return
  fi
  if [[ "${RESTORE_SYNC_SNAPSHOT}" != "auto" && "${RESTORE_SYNC_SNAPSHOT}" != "force" ]]; then
    echo "[compose-up] snapshot restore disabled (MOEX_RESTORE_SYNC_SNAPSHOT=${RESTORE_SYNC_SNAPSHOT})"
    return
  fi

  echo "[compose-up] importing shared snapshot from ${SYNC_BACKUP_FILE}..."
  if gunzip -c "${SYNC_BACKUP_FILE}" | docker compose exec -T db psql -v ON_ERROR_STOP=1 -U postgres -d fair_price >/dev/null; then
    echo "[compose-up] snapshot import completed"
  else
    echo "[compose-up] warning: failed to import shared snapshot" >&2
  fi
}


cert_files_accessible() {
  if [[ -r "${SSL_CERT_PATH}" && -r "${SSL_CERT_KEY_PATH}" ]]; then
    return 0
  fi
  if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    sudo test -r "${SSL_CERT_PATH}" -a -r "${SSL_CERT_KEY_PATH}"
    return $?
  fi
  return 1
}

build_nginx_args() {
  local args=("--server-name" "${SERVER_NAMES}")
  local https_enabled=0

  if [[ "${FORCE_HTTPS}" == "1" || "${FORCE_HTTPS,,}" == "true" || "${FORCE_HTTPS,,}" == "yes" ]]; then
    https_enabled=1
  elif cert_files_accessible; then
    https_enabled=1
  fi

  if [[ "${https_enabled}" == "1" ]]; then
    args+=("--https" "--ssl-cert" "${SSL_CERT_PATH}" "--ssl-key" "${SSL_CERT_KEY_PATH}")
    echo "[compose-up] nginx HTTPS mode enabled for ${PUBLIC_DOMAIN}" >&2
  else
    echo "[compose-up] nginx HTTP mode (certs are not accessible and MOEX_FORCE_HTTPS not enabled)" >&2
  fi

  printf '%s\n' "${args[@]}"
}

if command -v minikube >/dev/null 2>&1; then
  log_step "restoring host docker context (if minikube docker-env was enabled)"
  # shellcheck disable=SC2046
  # shellcheck disable=SC1090
  eval "$(minikube docker-env -u 2>/dev/null || true)"
fi

log_step "starting PostgreSQL before optional restore"
docker compose up -d db
for _ in $(seq 1 30); do
  if docker compose exec -T db pg_isready -U postgres -d fair_price >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
log_step "restoring shared DB snapshot only when safe"
import_snapshot_into_compose_db
log_step "starting docker compose application stack"
docker compose up -d --build --remove-orphans "$@"

log_step "compose mode is up"
echo "[compose-up] compose project: ${COMPOSE_PROJECT}"
echo "[compose-up] frontend loopback endpoint: http://${FRONTEND_BIND}:${FRONTEND_PORT}/"
echo "[compose-up] backend loopback endpoint: http://${BACKEND_BIND}:${BACKEND_PORT}/"
echo "[compose-up] public URL: https://${PUBLIC_DOMAIN}/"

if [[ -x "./scripts/configure-nginx-compose-proxy.sh" ]]; then
  log_step "switching nginx reverse-proxy to compose mode"
  if [[ -w "/etc/nginx/conf.d" ]]; then
    mapfile -t nginx_args < <(build_nginx_args)
    ./scripts/configure-nginx-compose-proxy.sh "${nginx_args[@]}" --reload || true
  elif command -v sudo >/dev/null 2>&1; then
    mapfile -t nginx_args < <(build_nginx_args)
    sudo ./scripts/configure-nginx-compose-proxy.sh "${nginx_args[@]}" --reload || true
  else
    echo "[compose-up] warning: no permissions to reload nginx. Run manually:" >&2
    echo "  sudo ./scripts/configure-nginx-compose-proxy.sh --reload" >&2
  fi
fi
