#!/bin/sh
set -eu
.venv/bin/python -m flask --app run db upgrade
exec .venv/bin/gunicorn --config gunicorn.conf.py run:app
