#!/usr/bin/env bash
set -euo pipefail

TEMPLATE_PATH="deploy/nginx/home-server-k8s.conf"
# Unified output path so home-network URL stays stable regardless of deployment mode.
OUTPUT_PATH="/etc/nginx/conf.d/moex.conf"
RELOAD=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      OUTPUT_PATH="$2"
      shift 2
      ;;
    --reload)
      RELOAD=true
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[nginx-k8s-proxy] error: required command not found: $cmd" >&2
    exit 1
  fi
}

require_cmd minikube
require_cmd awk

if [[ ! -f "$TEMPLATE_PATH" ]]; then
  echo "[nginx-k8s-proxy] error: template not found: $TEMPLATE_PATH" >&2
  exit 1
fi

MINIKUBE_IP="$(minikube ip | tr -d '[:space:]')"
if [[ -z "$MINIKUBE_IP" ]]; then
  echo "[nginx-k8s-proxy] error: unable to detect minikube ip" >&2
  exit 1
fi

echo "[nginx-k8s-proxy] using minikube ip: ${MINIKUBE_IP}"
mkdir -p "$(dirname "$OUTPUT_PATH")"
awk -v ip="$MINIKUBE_IP" '{gsub(/MINIKUBE_IP/, ip); print}' "$TEMPLATE_PATH" > "$OUTPUT_PATH"

echo "[nginx-k8s-proxy] generated: $OUTPUT_PATH"
if [[ "$OUTPUT_PATH" == "/etc/nginx/conf.d/moex.conf" && -f "/etc/nginx/conf.d/moex-k8s.conf" ]]; then
  rm -f /etc/nginx/conf.d/moex-k8s.conf
fi

if [[ "$RELOAD" == "true" ]]; then
  require_cmd nginx
  if nginx -t; then
    if command -v systemctl >/dev/null 2>&1; then
      systemctl reload nginx
    else
      nginx -s reload
    fi
    echo "[nginx-k8s-proxy] nginx reloaded"
  else
    echo "[nginx-k8s-proxy] error: nginx -t failed" >&2
    exit 1
  fi
else
  echo "[nginx-k8s-proxy] run with --reload to validate/reload nginx automatically"
fi
