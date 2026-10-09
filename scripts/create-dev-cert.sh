#!/bin/sh
set -eu

mkdir -p certs
openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 365 \
  -keyout certs/server.key \
  -out certs/server.crt \
  -subj '/CN=localhost' \
  -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1'
chmod 600 certs/server.key
printf 'Created a local development certificate in certs/.\n'
