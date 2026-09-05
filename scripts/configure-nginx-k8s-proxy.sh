#!/usr/bin/env bash
set -euo pipefail

TEMPLATE_PATH_HTTP="deploy/nginx/home-server-k8s.conf"
TEMPLATE_PATH_HTTPS="deploy/nginx/home-server-k8s-https.conf"
# Unified output path so home-network URL stays stable regardless of deployment mode.
OUTPUT_PATH="/etc/nginx/conf.d/moex.conf"
RELOAD=false
HTTPS=false
SERVER_NAME="moex.junnylab.ru"
SSL_CERT_PATH=""
SSL_CERT_KEY_PATH=""

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
    --https)
      HTTPS=true
      shift
      ;;
    --server-name)
      SERVER_NAME="$2"
      shift 2
      ;;
    --ssl-cert)
      SSL_CERT_PATH="$2"
      shift 2
      ;;
    --ssl-key)
      SSL_CERT_KEY_PATH="$2"
      shift 2
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

if [[ "$HTTPS" == "true" ]]; then
  TEMPLATE_PATH="$TEMPLATE_PATH_HTTPS"
  SSL_CERT_PATH="${SSL_CERT_PATH:-/etc/letsencrypt/live/junnylab.ru-0002/fullchain.pem}"
  SSL_CERT_KEY_PATH="${SSL_CERT_KEY_PATH:-/etc/letsencrypt/live/junnylab.ru-0002/privkey.pem}"
  if [[ ! -r "$SSL_CERT_PATH" || ! -r "$SSL_CERT_KEY_PATH" ]]; then
    echo "[nginx-k8s-proxy] error: TLS certificate or key is not readable" >&2
    echo "[nginx-k8s-proxy] certificate: $SSL_CERT_PATH" >&2
    echo "[nginx-k8s-proxy] key: $SSL_CERT_KEY_PATH" >&2
    exit 1
  fi
else
  TEMPLATE_PATH="$TEMPLATE_PATH_HTTP"
fi

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

mkdir -p "$(dirname "$OUTPUT_PATH")"
awk \
  -v frontend="$FRONTEND_ENDPOINT" \
  -v server_name="$SERVER_NAME" \
  -v ssl_cert_path="$SSL_CERT_PATH" \
  -v ssl_cert_key_path="$SSL_CERT_KEY_PATH" \
  '{
     gsub(/MINIKUBE_FRONTEND_ENDPOINT/, frontend);
     gsub(/SERVER_NAMES_PLACEHOLDER/, server_name);
     gsub(/SSL_CERT_PATH_PLACEHOLDER/, ssl_cert_path);
     gsub(/SSL_CERT_KEY_PATH_PLACEHOLDER/, ssl_cert_key_path);
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
