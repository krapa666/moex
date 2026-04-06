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
