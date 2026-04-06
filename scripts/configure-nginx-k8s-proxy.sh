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
require_cmd curl

if [[ ! -f "$TEMPLATE_PATH" ]]; then
  echo "[nginx-k8s-proxy] error: template not found: $TEMPLATE_PATH" >&2
  exit 1
fi

MINIKUBE_IP="$(minikube ip | tr -d '[:space:]')"
if [[ -z "$MINIKUBE_IP" ]]; then
  echo "[nginx-k8s-proxy] error: unable to detect minikube ip" >&2
  exit 1
fi

FRONTEND_ENDPOINT="${MINIKUBE_IP}:30080"
if curl -fsS --max-time 2 "http://127.0.0.1:30080/" >/dev/null 2>&1; then
  FRONTEND_ENDPOINT="127.0.0.1:30080"
  echo "[nginx-k8s-proxy] using localhost frontend endpoint: ${FRONTEND_ENDPOINT}"
elif curl -fsS --max-time 2 "http://${FRONTEND_ENDPOINT}/" >/dev/null 2>&1; then
  echo "[nginx-k8s-proxy] localhost endpoint unavailable; using minikube ip endpoint: ${FRONTEND_ENDPOINT}"
else
  echo "[nginx-k8s-proxy] warning: frontend endpoint is not reachable yet; generating config with ${FRONTEND_ENDPOINT}" >&2
fi

mkdir -p "$(dirname "$OUTPUT_PATH")"
awk -v endpoint="$FRONTEND_ENDPOINT" '{gsub(/MINIKUBE_FRONTEND_ENDPOINT/, endpoint); print}' "$TEMPLATE_PATH" > "$OUTPUT_PATH"

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
