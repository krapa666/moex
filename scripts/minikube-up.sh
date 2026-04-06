#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="moex"
BACKEND_IMAGE="krapa666/moex-backend:latest"
FRONTEND_IMAGE="krapa666/moex-frontend:latest"
SKIP_NGINX=false

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

echo "[minikube-up] starting minikube (if needed)..."
minikube start

echo "[minikube-up] enabling ingress addon..."
minikube addons enable ingress >/dev/null
wait_for_ingress_admission

echo "[minikube-up] switching docker daemon to minikube..."
# shellcheck disable=SC2046
# shellcheck disable=SC1090
eval "$(minikube docker-env)"

echo "[minikube-up] building backend image: ${BACKEND_IMAGE}"
docker build -t "${BACKEND_IMAGE}" backend

echo "[minikube-up] building frontend image: ${FRONTEND_IMAGE}"
docker build -t "${FRONTEND_IMAGE}" frontend

echo "[minikube-up] applying core manifests (without ingress)..."
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/postgres-pvc.yaml
kubectl apply -f k8s/postgres.yaml
kubectl apply -f k8s/backend.yaml
kubectl apply -f k8s/frontend.yaml

echo "[minikube-up] applying ingress..."
kubectl apply -f k8s/ingress.yaml

echo "[minikube-up] waiting for deployments..."
kubectl -n "${NAMESPACE}" rollout status deploy/postgres --timeout=180s
kubectl -n "${NAMESPACE}" rollout status deploy/backend --timeout=180s
kubectl -n "${NAMESPACE}" rollout status deploy/frontend --timeout=180s

echo "[minikube-up] done"
echo "[minikube-up] frontend URL (NodePort):"
if ! minikube service -n "${NAMESPACE}" frontend --url; then
  echo "[minikube-up] warning: failed to resolve service URL via minikube helper" >&2
fi
echo "[minikube-up] fallback URL: http://$(minikube ip):30080/"

echo "[minikube-up] ingress host: http://junibox/"

if [[ "${SKIP_NGINX}" == "true" ]]; then
  echo "[minikube-up] --skip-nginx set, reverse-proxy regeneration skipped"
elif [[ -x "./scripts/configure-nginx-k8s-proxy.sh" ]]; then
  echo "[minikube-up] regenerating nginx reverse-proxy config..."
  if [[ -w "/etc/nginx/conf.d" ]]; then
    ./scripts/configure-nginx-k8s-proxy.sh --reload || true
  elif command -v sudo >/dev/null 2>&1; then
    sudo ./scripts/configure-nginx-k8s-proxy.sh --reload || true
  else
    echo "[minikube-up] warning: no permissions to reload nginx. Run manually:" >&2
    echo "  sudo ./scripts/configure-nginx-k8s-proxy.sh --reload" >&2
  fi
fi
