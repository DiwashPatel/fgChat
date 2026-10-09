#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c 'import flask_socketio, flask_sqlalchemy, redis' >/dev/null 2>&1; then
  ./scripts/setup.sh
fi
if [ ! -f .env ]; then
  ./scripts/setup.sh
fi
set -a
. ./.env
set +a
.venv/bin/python -m flask --app run db upgrade
exec .venv/bin/python run.py
