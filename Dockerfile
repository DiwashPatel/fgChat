FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /srv/fgchat
RUN python -m venv /srv/fgchat/.venv
COPY requirements.txt ./requirements.txt
RUN .venv/bin/pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY migrations ./migrations
COPY run.py gunicorn.conf.py ./
COPY scripts/container-start.sh ./scripts/container-start.sh
RUN useradd --system --uid 10001 --create-home fgchat \
    && mkdir -p /srv/fgchat/instance \
    && chown -R fgchat:fgchat /srv/fgchat
USER fgchat
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=4s --start-period=20s --retries=3 \
  CMD .venv/bin/python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1
CMD ["./scripts/container-start.sh"]
