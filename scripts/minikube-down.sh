#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="moex"
KEEP_MINIKUBE=false

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

echo "[minikube-down] deleting Kubernetes resources..."
kubectl delete -k k8s --ignore-not-found=true

echo "[minikube-down] waiting namespace/${NAMESPACE} deletion (if exists)..."
for _ in $(seq 1 60); do
  if ! kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
  echo "[minikube-down] warning: namespace ${NAMESPACE} still exists, continuing" >&2
fi

echo "[minikube-down] restoring host docker context..."
# shellcheck disable=SC2046
# shellcheck disable=SC1090
eval "$(minikube docker-env -u)"

if [[ "${KEEP_MINIKUBE}" == "false" ]]; then
  echo "[minikube-down] stopping minikube..."
  minikube stop
else
  echo "[minikube-down] --keep-minikube set, cluster left running"
fi

echo "[minikube-down] done"
echo "[minikube-down] now you can run docker compose mode:"
echo "  ./scripts/compose-up.sh"
