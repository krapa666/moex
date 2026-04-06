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

if command -v minikube >/dev/null 2>&1; then
  echo "[compose-up] restoring host docker context (if minikube docker-env was enabled)..."
  # shellcheck disable=SC2046
  # shellcheck disable=SC1090
  eval "$(minikube docker-env -u 2>/dev/null || true)"
fi

echo "[compose-up] starting docker compose stack..."
docker compose up -d --build "$@"

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
