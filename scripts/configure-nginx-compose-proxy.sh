#!/usr/bin/env bash
set -euo pipefail

TEMPLATE_PATH="deploy/nginx/home-server.conf"
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

if [[ ! -f "$TEMPLATE_PATH" ]]; then
  echo "[nginx-compose-proxy] error: template not found: $TEMPLATE_PATH" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT_PATH")"
cp "$TEMPLATE_PATH" "$OUTPUT_PATH"
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
