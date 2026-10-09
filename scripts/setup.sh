#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -r requirements-dev.txt
if [ ! -f .env ]; then
  SECRET=$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))')
  DATABASE_PASSWORD=$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')
  printf 'FGCHAT_SECRET_KEY=%s\nPOSTGRES_PASSWORD=%s\n' "$SECRET" "$DATABASE_PASSWORD" > .env
  printf 'Created a local .env with random application and database secrets.\n'
fi
printf 'Setup complete. Start FgChat with ./scripts/dev.sh\n'
