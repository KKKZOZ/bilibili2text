#!/usr/bin/env bash
set -Eeuo pipefail

: "${FRONTEND_PORT:=6010}"
: "${BACKEND_HOST:=127.0.0.1}"
: "${BACKEND_PORT:=8000}"
: "${B2T_CONFIG:=/app/config.toml}"

if [[ ! -f "${B2T_CONFIG}" ]]; then
  echo "Config file not found: ${B2T_CONFIG}"
  echo "Please mount your config.toml, e.g."
  echo "  -v \$(pwd)/config.toml:/app/config.toml:ro"
  exit 1
fi

export FRONTEND_PORT BACKEND_HOST BACKEND_PORT
envsubst '${FRONTEND_PORT} ${BACKEND_HOST} ${BACKEND_PORT}' \
  < /etc/nginx/templates/default.conf.template \
  > /etc/nginx/conf.d/default.conf

uvicorn backend.main:app --app-dir /app/web-ui --host "${BACKEND_HOST}" --port "${BACKEND_PORT}" &
backend_pid=$!

nginx -g "daemon off;" &
nginx_pid=$!

cleanup() {
  kill "${backend_pid}" "${nginx_pid}" 2>/dev/null || true
  wait "${backend_pid}" 2>/dev/null || true
  wait "${nginx_pid}" 2>/dev/null || true
}

trap cleanup INT TERM

wait -n "${backend_pid}" "${nginx_pid}"
status=$?
cleanup
exit "${status}"
