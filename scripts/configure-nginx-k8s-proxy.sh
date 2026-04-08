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

require_cmd awk
require_cmd curl

if [[ ! -f "$TEMPLATE_PATH" ]]; then
  echo "[nginx-k8s-proxy] error: template not found: $TEMPLATE_PATH" >&2
  exit 1
fi

pick_endpoint() {
  local name="$1"
  local endpoint="$2"
  local health_path="$3"
  if curl -fsS --max-time 2 "http://${endpoint}${health_path}" >/dev/null 2>&1; then
    echo "[nginx-k8s-proxy] using ${name} endpoint: ${endpoint}" >&2
  else
    echo "[nginx-k8s-proxy] warning: ${name} endpoint is not reachable yet; using ${endpoint}" >&2
  fi
  printf '%s' "${endpoint}"
}

FRONTEND_ENDPOINT="$(pick_endpoint frontend '127.0.0.1:30080' '/')"
PROMETHEUS_ENDPOINT="$(pick_endpoint prometheus '127.0.0.1:39090' '/prometheus/-/ready')"
GRAFANA_ENDPOINT="$(pick_endpoint grafana '127.0.0.1:33000' '/api/health')"
LOKI_ENDPOINT="$(pick_endpoint loki '127.0.0.1:33100' '/ready')"

mkdir -p "$(dirname "$OUTPUT_PATH")"
awk \
  -v frontend="$FRONTEND_ENDPOINT" \
  -v prometheus="$PROMETHEUS_ENDPOINT" \
  -v grafana="$GRAFANA_ENDPOINT" \
  -v loki="$LOKI_ENDPOINT" \
  '{
     gsub(/MINIKUBE_FRONTEND_ENDPOINT/, frontend);
     gsub(/MINIKUBE_PROMETHEUS_ENDPOINT/, prometheus);
     gsub(/MINIKUBE_GRAFANA_ENDPOINT/, grafana);
     gsub(/MINIKUBE_LOKI_ENDPOINT/, loki);
     print
   }' "$TEMPLATE_PATH" > "$OUTPUT_PATH"

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
