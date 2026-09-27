#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="${ROOT_DIR}/web-ui/frontend"
NGINX_TEMPLATE="${ROOT_DIR}/docker/nginx.conf.template"
DIST_DIR="${FRONTEND_DIR}/dist"

: "${B2T_FRONTEND_PORT:=6010}"
# Linux host networking can reach a backend bound only to 127.0.0.1.
if [[ "$(uname -s)" == "Linux" ]]; then
  : "${B2T_NGINX_NETWORK:=host}"
else
  : "${B2T_NGINX_NETWORK:=bridge}"
fi
if [[ "${B2T_NGINX_NETWORK}" == "host" ]]; then
  : "${B2T_BACKEND_HOST:=127.0.0.1}"
else
  : "${B2T_BACKEND_HOST:=host.docker.internal}"
fi
: "${B2T_BACKEND_PORT:=8000}"
: "${B2T_NGINX_IMAGE:=nginx:1.27-alpine}"
: "${B2T_NGINX_CONTAINER:=bilibili-to-text-web}"

usage() {
  cat <<EOF
Usage: $(basename "$0") {up|down|restart|status|logs}

Environment:
  B2T_FRONTEND_PORT     Public frontend port. Default: 6010
  B2T_BACKEND_HOST      Backend host seen from Nginx. Default: 127.0.0.1 (host network), host.docker.internal (bridge)
  B2T_BACKEND_PORT      Backend port. Default: 8000
  B2T_NGINX_NETWORK     Docker network mode. Default: host on Linux, bridge elsewhere
  B2T_NGINX_IMAGE       Nginx image. Default: nginx:1.27-alpine
  B2T_NGINX_CONTAINER   Container name. Default: bilibili-to-text-web

Start the backend on the host separately, for example:
  uv run uvicorn backend.main:app --app-dir web-ui --host 0.0.0.0 --port 8000
EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

container_exists() {
  docker ps -a --format '{{.Names}}' | grep -Fxq "${B2T_NGINX_CONTAINER}"
}

container_running() {
  docker ps --format '{{.Names}}' | grep -Fxq "${B2T_NGINX_CONTAINER}"
}

build_frontend() {
  require_cmd bun
  echo "Building frontend..."
  (
    cd "${FRONTEND_DIR}"
    if [[ ! -d node_modules ]]; then
      bun install
    fi
    # Local Nginx owns /api. Do not inherit the Pages API origin from .env files.
    VITE_API_BASE_URL= bun run build
  )
}

docker_network_args=(--network "${B2T_NGINX_NETWORK}")
if [[ "${B2T_NGINX_NETWORK}" != "host" ]]; then
  docker_network_args+=(-p "${B2T_FRONTEND_PORT}:${B2T_FRONTEND_PORT}")
  if [[ "$(uname -s)" == "Linux" && "${B2T_BACKEND_HOST}" == "host.docker.internal" ]]; then
    docker_network_args+=(--add-host=host.docker.internal:host-gateway)
  fi
fi

start_nginx() {
  require_cmd docker
  build_frontend

  if container_running; then
    echo "Container ${B2T_NGINX_CONTAINER} is already running."
    echo "Frontend: http://127.0.0.1:${B2T_FRONTEND_PORT}"
    return
  fi

  if container_exists; then
    docker rm "${B2T_NGINX_CONTAINER}" >/dev/null
  fi

  echo "Starting Nginx container..."
  docker run -d \
    --name "${B2T_NGINX_CONTAINER}" \
    "${docker_network_args[@]}" \
    -e FRONTEND_PORT="${B2T_FRONTEND_PORT}" \
    -e BACKEND_HOST="${B2T_BACKEND_HOST}" \
    -e BACKEND_PORT="${B2T_BACKEND_PORT}" \
    -v "${DIST_DIR}:/usr/share/nginx/html:ro" \
    -v "${NGINX_TEMPLATE}:/etc/nginx/templates/default.conf.template:ro" \
    "${B2T_NGINX_IMAGE}" >/dev/null

  echo "Frontend: http://127.0.0.1:${B2T_FRONTEND_PORT}"
  echo "Backend proxy: http://${B2T_BACKEND_HOST}:${B2T_BACKEND_PORT}"
}

stop_nginx() {
  require_cmd docker
  if container_running; then
    docker stop "${B2T_NGINX_CONTAINER}" >/dev/null
    echo "Stopped ${B2T_NGINX_CONTAINER}."
  fi
  if container_exists; then
    docker rm "${B2T_NGINX_CONTAINER}" >/dev/null
    echo "Removed ${B2T_NGINX_CONTAINER}."
  else
    echo "Container ${B2T_NGINX_CONTAINER} is not present."
  fi
}

case "${1:-}" in
  up)
    start_nginx
    ;;
  down)
    stop_nginx
    ;;
  restart)
    stop_nginx
    start_nginx
    ;;
  status)
    require_cmd docker
    docker ps -a --filter "name=^/${B2T_NGINX_CONTAINER}$"
    ;;
  logs)
    require_cmd docker
    docker logs -f "${B2T_NGINX_CONTAINER}"
    ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac
