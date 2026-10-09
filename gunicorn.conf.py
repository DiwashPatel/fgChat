"""Gunicorn settings for the WebSocket-capable production entry point."""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
worker_class = "gthread"
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
threads = int(os.environ.get("GUNICORN_THREADS", "100"))
timeout = 60
graceful_timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")
