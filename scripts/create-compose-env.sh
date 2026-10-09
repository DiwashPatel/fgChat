#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
if [ ! -f .env ]; then
  : > .env
fi
if ! grep -Eq '^FGCHAT_SECRET_KEY=.+$' .env; then
  SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
  printf 'FGCHAT_SECRET_KEY=%s\n' "$SECRET" >> .env
fi
if ! grep -Eq '^POSTGRES_PASSWORD=.+$' .env; then
  DATABASE_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
  printf 'POSTGRES_PASSWORD=%s\n' "$DATABASE_PASSWORD" >> .env
fi
if ! grep -q '^FGCHAT_COOKIE_SECURE=' .env; then
  printf 'FGCHAT_COOKIE_SECURE=1\n' >> .env
fi
printf 'Compose environment is ready in .env.\n'
