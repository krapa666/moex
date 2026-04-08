#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="moex"
KEEP_MINIKUBE=false
PORT_FORWARD_PID_FILE="/tmp/moex-k8s-port-forward.pid"
PROMETHEUS_PORT_FORWARD_PID_FILE="/tmp/moex-k8s-prometheus-port-forward.pid"
GRAFANA_PORT_FORWARD_PID_FILE="/tmp/moex-k8s-grafana-port-forward.pid"
LOKI_PORT_FORWARD_PID_FILE="/tmp/moex-k8s-loki-port-forward.pid"
SYNC_BACKUP_DIR="./backups/mode-sync"
SYNC_BACKUP_FILE="${SYNC_BACKUP_DIR}/latest.sql.gz"
STEP=0

if [[ "${1:-}" == "--keep-minikube" ]]; then
  KEEP_MINIKUBE=true
fi

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[minikube-down] error: required command not found: $cmd" >&2
    exit 1
  fi
}

require_cmd kubectl
require_cmd minikube

log_step() {
  STEP=$((STEP + 1))
  echo "[minikube-down][step ${STEP}] $1"
}

export_k8s_db_snapshot() {
  if ! kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
    echo "[minikube-down] namespace ${NAMESPACE} not found, snapshot export skipped"
    return
  fi

  local pg_pod=""
  pg_pod="$(kubectl -n "${NAMESPACE}" get pod -l app=postgres -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  if [[ -z "${pg_pod}" ]]; then
    echo "[minikube-down] postgres pod not found, snapshot export skipped"
    return
  fi

  mkdir -p "${SYNC_BACKUP_DIR}"
  echo "[minikube-down] exporting DB snapshot from k8s pod ${pg_pod} to ${SYNC_BACKUP_FILE}..."
  if kubectl -n "${NAMESPACE}" exec -i "${pg_pod}" -- pg_dump --clean --if-exists --no-owner --no-privileges -U postgres -d fair_price | gzip -c > "${SYNC_BACKUP_FILE}.tmp"; then
    mv "${SYNC_BACKUP_FILE}.tmp" "${SYNC_BACKUP_FILE}"
    echo "source=minikube generated_at=$(date -Iseconds)" > "${SYNC_BACKUP_DIR}/latest.meta"
    echo "[minikube-down] snapshot export completed"
  else
    rm -f "${SYNC_BACKUP_FILE}.tmp"
    echo "[minikube-down] warning: failed to export DB snapshot from k8s" >&2
  fi
}

stop_port_forward() {
  local service="$1"
  local pid_file="$2"
  if [[ -f "${pid_file}" ]]; then
    local pf_pid
    pf_pid="$(cat "${pid_file}" 2>/dev/null || true)"
    if [[ -n "${pf_pid}" ]] && kill -0 "${pf_pid}" >/dev/null 2>&1; then
      echo "[minikube-down] stopping ${service} port-forward (pid: ${pf_pid})..."
      kill "${pf_pid}" || true
    fi
    rm -f "${pid_file}"
  fi
}

stop_port_forward frontend "${PORT_FORWARD_PID_FILE}"
stop_port_forward prometheus "${PROMETHEUS_PORT_FORWARD_PID_FILE}"
stop_port_forward grafana "${GRAFANA_PORT_FORWARD_PID_FILE}"
stop_port_forward loki "${LOKI_PORT_FORWARD_PID_FILE}"

log_step "exporting shared DB snapshot before shutdown"
export_k8s_db_snapshot
log_step "deleting Kubernetes resources"
kubectl delete -k k8s --ignore-not-found=true

log_step "waiting namespace/${NAMESPACE} deletion (if exists)"
for _ in $(seq 1 60); do
  if ! kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
  echo "[minikube-down] warning: namespace ${NAMESPACE} still exists, continuing" >&2
fi

log_step "restoring host docker context"
# shellcheck disable=SC2046
# shellcheck disable=SC1090
eval "$(minikube docker-env -u)"

if [[ "${KEEP_MINIKUBE}" == "false" ]]; then
  log_step "stopping minikube"
  minikube stop
else
  echo "[minikube-down] --keep-minikube set, cluster left running"
fi

log_step "minikube mode is down"
echo "[minikube-down] now you can run docker compose mode:"
echo "  ./scripts/compose-up.sh"
