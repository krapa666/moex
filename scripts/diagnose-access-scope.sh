#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-https://moex.ddns.net}"
LOCAL_HOST_URL="${2:-http://127.0.0.1}"

print_step() {
  echo
  echo "== $1 =="
}

run_curl() {
  local title="$1"
  shift
  print_step "$title"
  echo "+ curl $*"
  curl -ksS -D - "$@" -o /tmp/moex-access-body.json || true
  echo "-- body --"
  cat /tmp/moex-access-body.json || true
}

print_step "Environment"
echo "BASE_URL=${BASE_URL}"
echo "LOCAL_HOST_URL=${LOCAL_HOST_URL}"

auth_me_path="/api/auth/me"

run_curl "Public URL (as-is)" "${BASE_URL}${auth_me_path}"
run_curl "Local host URL (as-is, may redirect to HTTPS)" "${LOCAL_HOST_URL}${auth_me_path}"
run_curl "Local host URL (follow redirects)" -L "${LOCAL_HOST_URL}${auth_me_path}"
run_curl "Local host URL + forced local scope header (follow redirects)" -L -H "X-Moex-Access-Scope: local" "${LOCAL_HOST_URL}${auth_me_path}"
run_curl "Local host URL + forced internet scope header (follow redirects)" -L -H "X-Moex-Access-Scope: internet" "${LOCAL_HOST_URL}${auth_me_path}"
run_curl "Local host URL + explicit X-Forwarded-For private IP (follow redirects)" -L -H "X-Forwarded-For: 192.168.1.123" "${LOCAL_HOST_URL}${auth_me_path}"
run_curl "Local host URL + explicit X-Forwarded-For public IP (follow redirects)" -L -H "X-Forwarded-For: 8.8.8.8" "${LOCAL_HOST_URL}${auth_me_path}"

print_step "Nginx active config excerpt (/etc/nginx/conf.d/moex.conf)"
if [[ -r /etc/nginx/conf.d/moex.conf ]]; then
  rg -n "moex_access_scope|X-Moex-Access-Scope|location / \{|location /backend/|server_name" /etc/nginx/conf.d/moex.conf || true
else
  echo "No read access to /etc/nginx/conf.d/moex.conf"
fi

print_step "Recent nginx access log lines"
if [[ -r /var/log/nginx/access.log ]]; then
  tail -n 20 /var/log/nginx/access.log || true
else
  echo "No read access to /var/log/nginx/access.log"
fi

print_step "Expected interpretation"
cat <<TXT
- /api/auth/me should return {"username":"local-network","is_admin":true} for LAN requests.
- If it returns guest from LOCAL_HOST_URL, nginx likely does not pass X-Moex-Access-Scope or passes internet.
- If forced header local still returns guest, backend container is not running updated image/code.
TXT

print_step "Backend container direct probe (if docker compose available)"
if command -v docker >/dev/null 2>&1; then
  docker compose ps backend >/dev/null 2>&1 && docker compose exec -T backend python - <<'PY' || true
import urllib.request
for url in ["http://127.0.0.1:8000/api/health", "http://127.0.0.1:8000/api/auth/me"]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            print(url, r.status, r.read().decode())
    except Exception as e:
        print(url, "ERROR", e)
PY
else
  echo "docker command not found"
fi
