#!/bin/sh
# Entrypoint dev/prod. Idempoten: aman dijalankan berulang.
set -eu

if [ "${TF_SKIP_SETUP:-0}" != "1" ]; then
  python manage.py migrate --noinput
  # Tabel cache DB untuk rate limit login (rancangan §6.2).
  python manage.py createcachetable
fi

exec "$@"
