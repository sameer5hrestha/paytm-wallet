#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then
  umask 077
  printf 'ADMIN_KEY=%s\nDB_PASSWORD=%s\n' "$(openssl rand -hex 32)" "$(openssl rand -hex 24)" > .env
fi
if docker compose version >/dev/null 2>&1; then
  docker compose up --build -d --wait
else
  docker-compose up --build -d --wait
fi
