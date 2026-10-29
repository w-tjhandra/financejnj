# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Aset: Tailwind standalone CLI, versi dipatok + checksum (rancangan §1.7).
# Tidak ada Node/npm di stack.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS assets

ARG TAILWIND_VERSION=3.4.17
ARG TAILWIND_SHA256=7d24f7fa191d2193b78cd5f5a42a6093e14409521908529f42d80b11fde1f1d4

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /usr/local/bin/tailwindcss \
      "https://github.com/tailwindlabs/tailwindcss/releases/download/v${TAILWIND_VERSION}/tailwindcss-linux-x64" \
 && echo "${TAILWIND_SHA256}  /usr/local/bin/tailwindcss" | sha256sum -c - \
 && chmod +x /usr/local/bin/tailwindcss

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

# Dependensi sistem WeasyPrint (Pango/Cairo/GDK-Pixbuf/fontconfig) + font DejaVu
# agar PDF deterministik walau host tidak punya font.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libpango-1.0-0 \
      libpangoft2-1.0-0 \
      libharfbuzz0b \
      libcairo2 \
      libgdk-pixbuf-2.0-0 \
      libffi8 \
      shared-mime-info \
      fontconfig \
      fonts-dejavu-core \
      libjpeg62-turbo \
      libopenjp2-7 \
 && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 app \
 && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash app

WORKDIR /app

COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir ".[dev]"

COPY --chown=app:app . .

# Tailwind tersedia di image agar `make css` tidak butuh Node.
COPY --from=assets /usr/local/bin/tailwindcss /usr/local/bin/tailwindcss

# Bangun ulang CSS dari sumber agar image tidak pernah memakai CSS basi.
RUN tailwindcss -c tailwind.config.js -i static/src/input.css -o static/css/app.css --minify \
 && mkdir -p staticfiles media \
 && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)" || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
