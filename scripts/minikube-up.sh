#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="moex"
BACKEND_IMAGE="krapa666/moex-backend:latest"
FRONTEND_IMAGE="krapa666/moex-frontend:latest"

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

echo "[minikube-up] starting minikube (if needed)..."
minikube start

echo "[minikube-up] enabling ingress addon..."
minikube addons enable ingress >/dev/null

echo "[minikube-up] switching docker daemon to minikube..."
# shellcheck disable=SC2046
# shellcheck disable=SC1090
eval "$(minikube docker-env)"

echo "[minikube-up] building backend image: ${BACKEND_IMAGE}"
docker build -t "${BACKEND_IMAGE}" backend

echo "[minikube-up] building frontend image: ${FRONTEND_IMAGE}"
docker build -t "${FRONTEND_IMAGE}" frontend

echo "[minikube-up] applying manifests..."
kubectl apply -k k8s

echo "[minikube-up] waiting for deployments..."
kubectl -n "${NAMESPACE}" rollout status deploy/postgres --timeout=180s
kubectl -n "${NAMESPACE}" rollout status deploy/backend --timeout=180s
kubectl -n "${NAMESPACE}" rollout status deploy/frontend --timeout=180s

echo "[minikube-up] done"
echo "[minikube-up] frontend URL (NodePort helper):"
minikube service -n "${NAMESPACE}" frontend --url

echo "[minikube-up] ingress host: http://junibox/"
echo "[minikube-up] if junibox does not resolve to minikube ingress, use deploy/nginx/home-server-k8s.conf"
