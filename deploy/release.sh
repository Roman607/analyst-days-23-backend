#!/usr/bin/env bash
set -euo pipefail

backend_sha=$1
frontend_sha=$2
site='https://ad23-track.89.23.100.193.nip.io:8445'
tls_dir=/opt/ad23-track/letsencrypt
release_dir=$(pwd -P)

for sha in "$backend_sha" "$frontend_sha"; do
  [[ $sha =~ ^[0-9a-f]{40}$ ]] || exit 2
done
test -s "$release_dir/program.sqlite3"
test -s "$tls_dir/live/ad23-track.89.23.100.193.nip.io/fullchain.pem"

# Serialize Compose changes on the server, including releases started by hand.
exec 9>/opt/ad23-track/.deploy.lock
flock -x 9
cat > release.env <<ENV
BACKEND_IMAGE=ghcr.io/roman607/analyst-days-23-backend:$backend_sha
FRONTEND_IMAGE=ghcr.io/roman607/analyst-days-23-frontend:$frontend_sha
PROGRAM_FILE=$release_dir/program.sqlite3
TLS_DIR=$tls_dir
ENV
compose=(docker compose --project-name ad23-track --env-file release.env)
echo "Backend $backend_sha"
echo "Frontend $frontend_sha"
"${compose[@]}" config --quiet
"${compose[@]}" pull
"${compose[@]}" up --detach --wait --wait-timeout 90 --force-recreate
"${compose[@]}" restart backend frontend proxy
attempts=30
until curl -fsS --max-time 5 "$site/api/health" >/dev/null; do
  attempts=$((attempts - 1))
  if (( attempts == 0 )); then
    "${compose[@]}" ps >&2
    exit 1
  fi
  sleep 2
done
