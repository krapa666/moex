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
PUBLIC_DOMAIN="${MOEX_PUBLIC_DOMAIN:-${MOEX_SERVER_NAME:-moex.ddns.net}}"
SSL_CERT_PATH="${MOEX_SSL_CERT_PATH:-/etc/letsencrypt/live/${PUBLIC_DOMAIN}/fullchain.pem}"
SSL_CERT_KEY_PATH="${MOEX_SSL_CERT_KEY_PATH:-/etc/letsencrypt/live/${PUBLIC_DOMAIN}/privkey.pem}"

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

build_nginx_args() {
  local args=("--server-name" "${PUBLIC_DOMAIN}")
  if [[ -f "${SSL_CERT_PATH}" && -f "${SSL_CERT_KEY_PATH}" ]]; then
    echo "[compose-up] detected TLS certificate for ${PUBLIC_DOMAIN}, enabling HTTPS nginx config"
    args+=("--https" "--ssl-cert" "${SSL_CERT_PATH}" "--ssl-key" "${SSL_CERT_KEY_PATH}")
  else
    echo "[compose-up] TLS certificate not found for ${PUBLIC_DOMAIN}; keeping HTTP nginx config"
    echo "[compose-up] expected cert files:"
    echo "  - ${SSL_CERT_PATH}"
    echo "  - ${SSL_CERT_KEY_PATH}"
  fi
  printf '%s\n' "${args[@]}"
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
echo "[compose-up] frontend: http://${PUBLIC_DOMAIN}/"

if [[ -x "./scripts/configure-nginx-compose-proxy.sh" ]]; then
  log_step "switching nginx reverse-proxy to compose mode"
  mapfile -t nginx_args < <(build_nginx_args)
  if [[ -w "/etc/nginx/conf.d" ]]; then
    ./scripts/configure-nginx-compose-proxy.sh "${nginx_args[@]}" --reload || true
  elif command -v sudo >/dev/null 2>&1; then
    sudo ./scripts/configure-nginx-compose-proxy.sh "${nginx_args[@]}" --reload || true
  else
    echo "[compose-up] warning: no permissions to reload nginx. Run manually:" >&2
    echo "  sudo ./scripts/configure-nginx-compose-proxy.sh ${nginx_args[*]} --reload" >&2
  fi
fi
