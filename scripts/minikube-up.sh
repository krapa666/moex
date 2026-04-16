#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="moex"
BACKEND_IMAGE="krapa666/moex-backend:latest"
FRONTEND_IMAGE="krapa666/moex-frontend:latest"
SKIP_NGINX=false
PORT_FORWARD_PID_FILE="/tmp/moex-k8s-port-forward.pid"
PORT_FORWARD_LOG_FILE="/tmp/moex-k8s-port-forward.log"
PROMETHEUS_PORT_FORWARD_PID_FILE="/tmp/moex-k8s-prometheus-port-forward.pid"
PROMETHEUS_PORT_FORWARD_LOG_FILE="/tmp/moex-k8s-prometheus-port-forward.log"
GRAFANA_PORT_FORWARD_PID_FILE="/tmp/moex-k8s-grafana-port-forward.pid"
GRAFANA_PORT_FORWARD_LOG_FILE="/tmp/moex-k8s-grafana-port-forward.log"
LOKI_PORT_FORWARD_PID_FILE="/tmp/moex-k8s-loki-port-forward.pid"
LOKI_PORT_FORWARD_LOG_FILE="/tmp/moex-k8s-loki-port-forward.log"
SYNC_BACKUP_DIR="./backups/mode-sync"
SYNC_BACKUP_FILE="${SYNC_BACKUP_DIR}/latest.sql.gz"
PUBLIC_DOMAIN="${MOEX_PUBLIC_DOMAIN:-${MOEX_SERVER_NAME:-moex.ddns.net}}"
SSL_CERT_PATH="${MOEX_SSL_CERT_PATH:-/etc/letsencrypt/live/${PUBLIC_DOMAIN}/fullchain.pem}"
SSL_CERT_KEY_PATH="${MOEX_SSL_CERT_KEY_PATH:-/etc/letsencrypt/live/${PUBLIC_DOMAIN}/privkey.pem}"
FORCE_HTTPS="${MOEX_FORCE_HTTPS:-}"
STEP=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-nginx)
      SKIP_NGINX=true
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
    echo "[minikube-up] error: required command not found: $cmd" >&2
    exit 1
  fi
}

require_cmd minikube
require_cmd kubectl
require_cmd docker
require_cmd curl

log_step() {
  STEP=$((STEP + 1))
  echo "[minikube-up][step ${STEP}] $1"
}

start_frontend_port_forward() {
  if [[ -f "${PORT_FORWARD_PID_FILE}" ]]; then
    local existing_pid
    existing_pid="$(cat "${PORT_FORWARD_PID_FILE}" 2>/dev/null || true)"
    if [[ -n "${existing_pid}" ]] && kill -0 "${existing_pid}" >/dev/null 2>&1; then
      echo "[minikube-up] frontend port-forward already running (pid: ${existing_pid})"
      return
    fi
    rm -f "${PORT_FORWARD_PID_FILE}"
  fi

  echo "[minikube-up] starting frontend port-forward on 127.0.0.1:30080..."
  nohup kubectl -n "${NAMESPACE}" port-forward svc/frontend 30080:80 --address 127.0.0.1 >"${PORT_FORWARD_LOG_FILE}" 2>&1 &
  local pf_pid=$!
  echo "${pf_pid}" > "${PORT_FORWARD_PID_FILE}"

  for _ in $(seq 1 30); do
    if curl -fsS --max-time 2 "http://127.0.0.1:30080/" >/dev/null 2>&1; then
      echo "[minikube-up] frontend port-forward is ready (pid: ${pf_pid})"
      return
    fi
    sleep 1
  done

  echo "[minikube-up] warning: port-forward did not become ready in time; see ${PORT_FORWARD_LOG_FILE}" >&2
}

start_service_port_forward() {
  local service="$1"
  local local_port="$2"
  local remote_port="$3"
  local pid_file="$4"
  local log_file="$5"
  local health_url="$6"

  if [[ -f "${pid_file}" ]]; then
    local existing_pid
    existing_pid="$(cat "${pid_file}" 2>/dev/null || true)"
    if [[ -n "${existing_pid}" ]] && kill -0 "${existing_pid}" >/dev/null 2>&1; then
      echo "[minikube-up] ${service} port-forward already running (pid: ${existing_pid})"
      return
    fi
    rm -f "${pid_file}"
  fi

  echo "[minikube-up] starting ${service} port-forward on 127.0.0.1:${local_port}..."
  nohup kubectl -n "${NAMESPACE}" port-forward "svc/${service}" "${local_port}:${remote_port}" --address 127.0.0.1 >"${log_file}" 2>&1 &
  local pf_pid=$!
  echo "${pf_pid}" > "${pid_file}"

  for _ in $(seq 1 30); do
    if curl -fsS --max-time 2 "${health_url}" >/dev/null 2>&1; then
      echo "[minikube-up] ${service} port-forward is ready (pid: ${pf_pid})"
      return
    fi
    sleep 1
  done

  echo "[minikube-up] warning: ${service} port-forward did not become ready in time; see ${log_file}" >&2
}

import_snapshot_into_k8s_db() {
  if [[ ! -s "${SYNC_BACKUP_FILE}" ]]; then
    echo "[minikube-up] no shared snapshot found, import skipped"
    return
  fi

  local pg_pod=""
  pg_pod="$(kubectl -n "${NAMESPACE}" get pod -l app=postgres -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  if [[ -z "${pg_pod}" ]]; then
    echo "[minikube-up] postgres pod not found, import skipped" >&2
    return
  fi

  echo "[minikube-up] importing shared snapshot into k8s postgres (${pg_pod})..."
  if gunzip -c "${SYNC_BACKUP_FILE}" | kubectl -n "${NAMESPACE}" exec -i "${pg_pod}" -- psql -v ON_ERROR_STOP=1 -U postgres -d fair_price >/dev/null; then
    echo "[minikube-up] snapshot import completed"
  else
    echo "[minikube-up] warning: failed to import shared snapshot into k8s postgres" >&2
  fi
}

wait_for_ingress_admission() {
  echo "[minikube-up] waiting for ingress-nginx controller rollout..."
  kubectl -n ingress-nginx rollout status deploy/ingress-nginx-controller --timeout=240s

  echo "[minikube-up] waiting for ingress admission endpoints..."
  for _ in $(seq 1 60); do
    endpoint_ip="$(kubectl -n ingress-nginx get endpoints ingress-nginx-controller-admission -o jsonpath='{.subsets[0].addresses[0].ip}' 2>/dev/null || true)"
    if [[ -n "${endpoint_ip}" ]]; then
      echo "[minikube-up] ingress admission endpoint is ready: ${endpoint_ip}"
      return
    fi
    sleep 2
  done

  echo "[minikube-up] error: ingress admission endpoint did not become ready in time" >&2
  exit 1
}

build_nginx_args() {
  local args=("--server-name" "${PUBLIC_DOMAIN}")
  if [[ -n "${MOEX_SSL_CERT_PATH:-}" ]]; then
    args+=("--ssl-cert" "${SSL_CERT_PATH}")
  fi
  if [[ -n "${MOEX_SSL_CERT_KEY_PATH:-}" ]]; then
    args+=("--ssl-key" "${SSL_CERT_KEY_PATH}")
  fi
  if [[ "${FORCE_HTTPS}" == "1" || "${FORCE_HTTPS,,}" == "true" || "${FORCE_HTTPS,,}" == "yes" ]]; then
    args+=("--https")
    echo "[minikube-up] MOEX_FORCE_HTTPS enabled, forcing HTTPS nginx config" >&2
  else
    echo "[minikube-up] nginx mode auto-detection delegated to configure-nginx-k8s-proxy.sh" >&2
  fi
  printf '%s\n' "${args[@]}"
}

log_step "starting minikube (if needed)"
minikube start

log_step "enabling ingress addon"
minikube addons enable ingress >/dev/null
wait_for_ingress_admission

log_step "switching docker daemon to minikube"
# shellcheck disable=SC2046
# shellcheck disable=SC1090
eval "$(minikube docker-env)"

log_step "building backend image: ${BACKEND_IMAGE}"
docker build -t "${BACKEND_IMAGE}" backend

log_step "building frontend image: ${FRONTEND_IMAGE}"
docker build -t "${FRONTEND_IMAGE}" frontend

log_step "applying core manifests (without ingress)"
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/postgres-pvc.yaml
kubectl apply -f k8s/postgres.yaml
kubectl apply -f k8s/backend.yaml
kubectl apply -f k8s/frontend.yaml
kubectl apply -f k8s/prometheus.yaml
kubectl apply -f k8s/loki.yaml
kubectl apply -f k8s/grafana.yaml

log_step "applying ingress"
kubectl apply -f k8s/ingress.yaml

log_step "waiting for deployments and importing snapshot"
kubectl -n "${NAMESPACE}" rollout status deploy/postgres --timeout=180s
import_snapshot_into_k8s_db
kubectl -n "${NAMESPACE}" rollout status deploy/backend --timeout=180s
kubectl -n "${NAMESPACE}" rollout status deploy/frontend --timeout=180s
kubectl -n "${NAMESPACE}" rollout status deploy/prometheus --timeout=180s
kubectl -n "${NAMESPACE}" rollout status deploy/loki --timeout=180s
kubectl -n "${NAMESPACE}" rollout status deploy/grafana --timeout=180s
start_frontend_port_forward
start_service_port_forward prometheus 39090 9090 "${PROMETHEUS_PORT_FORWARD_PID_FILE}" "${PROMETHEUS_PORT_FORWARD_LOG_FILE}" "http://127.0.0.1:39090/prometheus/-/ready"
start_service_port_forward grafana 33000 3000 "${GRAFANA_PORT_FORWARD_PID_FILE}" "${GRAFANA_PORT_FORWARD_LOG_FILE}" "http://127.0.0.1:33000/api/health"
start_service_port_forward loki 33100 3100 "${LOKI_PORT_FORWARD_PID_FILE}" "${LOKI_PORT_FORWARD_LOG_FILE}" "http://127.0.0.1:33100/ready"

log_step "minikube mode is up"
echo "[minikube-up] frontend URL (NodePort):"
if ! minikube service -n "${NAMESPACE}" frontend --url; then
  echo "[minikube-up] warning: failed to resolve service URL via minikube helper" >&2
fi
echo "[minikube-up] fallback URL: http://$(minikube ip):30080/"
echo "[minikube-up] localhost NodePort URL: http://127.0.0.1:30080/"
echo "[minikube-up] monitoring URLs via ingress:"
echo "  - http://${PUBLIC_DOMAIN}/prometheus/"
echo "  - http://${PUBLIC_DOMAIN}/grafana/"
echo "  - http://${PUBLIC_DOMAIN}/loki/"

echo "[minikube-up] home-network URL (via local nginx reverse-proxy): http://${PUBLIC_DOMAIN}/"

if [[ "${SKIP_NGINX}" == "true" ]]; then
  echo "[minikube-up] --skip-nginx set, reverse-proxy regeneration skipped"
elif [[ -x "./scripts/configure-nginx-k8s-proxy.sh" ]]; then
  echo "[minikube-up] regenerating nginx reverse-proxy config..."
  mapfile -t nginx_args < <(build_nginx_args)
  if [[ -w "/etc/nginx/conf.d" ]]; then
    ./scripts/configure-nginx-k8s-proxy.sh "${nginx_args[@]}" --reload || true
  elif command -v sudo >/dev/null 2>&1; then
    sudo ./scripts/configure-nginx-k8s-proxy.sh "${nginx_args[@]}" --reload || true
  else
    echo "[minikube-up] warning: no permissions to reload nginx. Run manually:" >&2
    echo "  sudo ./scripts/configure-nginx-k8s-proxy.sh ${nginx_args[*]} --reload" >&2
  fi
fi
