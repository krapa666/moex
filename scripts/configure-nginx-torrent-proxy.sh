#!/usr/bin/env bash
set -euo pipefail

TEMPLATE_PATH="deploy/nginx/junibox-torrent-https.conf"
OUTPUT_PATH="/etc/nginx/conf.d/junibox-torrent.conf"
SERVER_NAMES="junibox junibox.junnylab.ru"
SSL_CERT_PATH="/etc/letsencrypt/live/junnylab.ru-0002/fullchain.pem"
SSL_CERT_KEY_PATH="/etc/letsencrypt/live/junnylab.ru-0002/privkey.pem"
RELOAD=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      OUTPUT_PATH="$2"
      shift 2
      ;;
    --server-name)
      SERVER_NAMES="$2"
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

if [[ ! -r "$SSL_CERT_PATH" || ! -r "$SSL_CERT_KEY_PATH" ]]; then
  echo "[nginx-torrent-proxy] error: TLS certificate or key is not readable" >&2
  echo "[nginx-torrent-proxy] certificate: $SSL_CERT_PATH" >&2
  echo "[nginx-torrent-proxy] key: $SSL_CERT_KEY_PATH" >&2
  exit 1
fi

if [[ ! -f "$TEMPLATE_PATH" ]]; then
  echo "[nginx-torrent-proxy] error: template not found: $TEMPLATE_PATH" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT_PATH")"
awk \
  -v server_names="$SERVER_NAMES" \
  -v ssl_cert_path="$SSL_CERT_PATH" \
  -v ssl_cert_key_path="$SSL_CERT_KEY_PATH" \
  '{
     gsub(/TORRENT_SERVER_NAMES_PLACEHOLDER/, server_names);
     gsub(/SSL_CERT_PATH_PLACEHOLDER/, ssl_cert_path);
     gsub(/SSL_CERT_KEY_PATH_PLACEHOLDER/, ssl_cert_key_path);
     print
   }' "$TEMPLATE_PATH" > "$OUTPUT_PATH"
echo "[nginx-torrent-proxy] generated: $OUTPUT_PATH"

if [[ "$RELOAD" == "true" ]]; then
  if ! command -v nginx >/dev/null 2>&1; then
    echo "[nginx-torrent-proxy] error: nginx command not found" >&2
    exit 1
  fi
  nginx -t
  if command -v systemctl >/dev/null 2>&1; then
    systemctl reload nginx
  else
    nginx -s reload
  fi
  echo "[nginx-torrent-proxy] nginx reloaded"
else
  echo "[nginx-torrent-proxy] run with --reload to validate/reload nginx automatically"
fi
