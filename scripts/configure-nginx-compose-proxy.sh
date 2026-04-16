#!/usr/bin/env bash
set -euo pipefail

TEMPLATE_PATH_HTTP="deploy/nginx/home-server.conf"
TEMPLATE_PATH_HTTPS="deploy/nginx/home-server-https.conf"
OUTPUT_PATH="/etc/nginx/conf.d/moex.conf"
RELOAD=false
HTTPS=false
SERVER_NAME="${MOEX_PUBLIC_DOMAIN:-${MOEX_SERVER_NAME:-moex.ddns.net}}"
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

if [[ "$HTTPS" == "true" ]]; then
  TEMPLATE_PATH="$TEMPLATE_PATH_HTTPS"
  SSL_CERT_PATH="${SSL_CERT_PATH:-/etc/letsencrypt/live/${SERVER_NAME}/fullchain.pem}"
  SSL_CERT_KEY_PATH="${SSL_CERT_KEY_PATH:-/etc/letsencrypt/live/${SERVER_NAME}/privkey.pem}"
else
  auto_cert_path="${SSL_CERT_PATH:-/etc/letsencrypt/live/${SERVER_NAME}/fullchain.pem}"
  auto_key_path="${SSL_CERT_KEY_PATH:-/etc/letsencrypt/live/${SERVER_NAME}/privkey.pem}"
  if [[ -f "${auto_cert_path}" && -f "${auto_key_path}" ]]; then
    echo "[nginx-compose-proxy] detected existing TLS certificate for ${SERVER_NAME}; auto-enabling HTTPS template"
    HTTPS=true
    TEMPLATE_PATH="$TEMPLATE_PATH_HTTPS"
    SSL_CERT_PATH="${auto_cert_path}"
    SSL_CERT_KEY_PATH="${auto_key_path}"
  else
    TEMPLATE_PATH="$TEMPLATE_PATH_HTTP"
  fi
fi

if [[ ! -f "$TEMPLATE_PATH" ]]; then
  echo "[nginx-compose-proxy] error: template not found: $TEMPLATE_PATH" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT_PATH")"
if [[ "$HTTPS" == "true" ]]; then
  awk \
    -v server_name="$SERVER_NAME" \
    -v ssl_cert_path="$SSL_CERT_PATH" \
    -v ssl_cert_key_path="$SSL_CERT_KEY_PATH" \
    '{
       gsub(/SERVER_NAMES_PLACEHOLDER/, server_name);
       gsub(/SSL_CERT_PATH_PLACEHOLDER/, ssl_cert_path);
       gsub(/SSL_CERT_KEY_PATH_PLACEHOLDER/, ssl_cert_key_path);
       print
     }' "$TEMPLATE_PATH" > "$OUTPUT_PATH"
else
  cp "$TEMPLATE_PATH" "$OUTPUT_PATH"
fi
echo "[nginx-compose-proxy] generated: $OUTPUT_PATH"

if [[ "$OUTPUT_PATH" == "/etc/nginx/conf.d/moex.conf" && -f "/etc/nginx/conf.d/moex-k8s.conf" ]]; then
  rm -f /etc/nginx/conf.d/moex-k8s.conf
fi

if [[ "$RELOAD" == "true" ]]; then
  if ! command -v nginx >/dev/null 2>&1; then
    echo "[nginx-compose-proxy] error: nginx command not found" >&2
    exit 1
  fi
  if nginx -t; then
    if command -v systemctl >/dev/null 2>&1; then
      systemctl reload nginx
    else
      nginx -s reload
    fi
    echo "[nginx-compose-proxy] nginx reloaded"
  else
    echo "[nginx-compose-proxy] error: nginx -t failed" >&2
    exit 1
  fi
else
  echo "[nginx-compose-proxy] run with --reload to validate/reload nginx automatically"
fi
