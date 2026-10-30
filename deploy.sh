#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT_DIR/.env"
COMPOSE_FILE="$ROOT_DIR/docker-compose.prod.yml"

fail() {
  printf 'Deploy dibatalkan: %s\n' "$1" >&2
  exit 1
}

read_env_value() {
  awk -F= -v key="$1" '$1 == key { print substr($0, length($1) + 2); exit }' "$ENV_FILE"
}

[[ -f "$ENV_FILE" ]] || fail "file .env belum ada. Salin .env.production.example ke .env lalu isi nilainya."
[[ -f "$COMPOSE_FILE" ]] || fail "docker-compose.prod.yml tidak ditemukan."
command -v docker >/dev/null 2>&1 || fail "Docker belum terpasang."
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 belum tersedia."
command -v git >/dev/null 2>&1 || fail "Git belum terpasang."

for key in DJANGO_SECRET_KEY DJANGO_ALLOWED_HOSTS POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD; do
  value="$(read_env_value "$key")"
  [[ -n "$value" ]] || fail "$key wajib diisi di .env."
done

secret_key="$(read_env_value DJANGO_SECRET_KEY)"
db_password="$(read_env_value POSTGRES_PASSWORD)"
allowed_hosts="$(read_env_value DJANGO_ALLOWED_HOSTS)"
[[ ${#secret_key} -ge 50 && "$secret_key" != REPLACE_* ]] || fail "DJANGO_SECRET_KEY harus berupa secret acak minimal 50 karakter."
[[ ${#db_password} -ge 20 && "$db_password" != REPLACE_* && "$db_password" != telur_dev ]] || fail "POSTGRES_PASSWORD harus berupa password acak minimal 20 karakter."
[[ "$allowed_hosts" != *"*"* ]] || fail "DJANGO_ALLOWED_HOSTS tidak boleh menggunakan wildcard (*)."

cd "$ROOT_DIR"
branch="$(git branch --show-current)"
[[ "$branch" == main ]] || fail "branch aktif harus main, saat ini: ${branch:-detached HEAD}."
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  fail "worktree memiliki perubahan lokal. Commit atau simpan perubahan sebelum deploy."
fi

git pull --ff-only origin main

compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
"${compose[@]}" config --quiet
mkdir -p "$ROOT_DIR/backups"
chmod 700 "$ROOT_DIR/backups"

db_container="$("${compose[@]}" ps -q db)"
if [[ -n "$db_container" ]] && [[ "$(docker inspect -f '{{.State.Running}}' "$db_container")" == true ]]; then
  backup_file="$ROOT_DIR/backups/telur-finance-$(date +%Y%m%d-%H%M%S).dump"
  printf 'Membuat backup database sebelum deploy...\n'
  if ! "${compose[@]}" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' >"$backup_file"; then
    rm -f "$backup_file"
    fail "backup database gagal; service tidak diperbarui."
  fi
  chmod 600 "$backup_file"
  printf 'Backup tersimpan di backups/%s\n' "$(basename "$backup_file")"
fi

printf 'Build dan jalankan seluruh service produksi...\n'
"${compose[@]}" up -d --build --remove-orphans

wait_for_health() {
  local service="$1"
  local container_id status attempt

  for ((attempt = 1; attempt <= 60; attempt++)); do
    container_id="$("${compose[@]}" ps -q "$service")"
    if [[ -n "$container_id" ]]; then
      status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")"
      [[ "$status" == healthy ]] && return 0
      if [[ "$status" == unhealthy || "$status" == exited || "$status" == dead ]]; then
        "${compose[@]}" logs --tail=80 "$service" >&2
        fail "service $service berstatus $status."
      fi
    fi
    sleep 2
  done

  "${compose[@]}" logs --tail=80 "$service" >&2
  fail "service $service belum sehat setelah 120 detik."
}

for service in db app web; do
  printf 'Menunggu health check %s...\n' "$service"
  wait_for_health "$service"
done

"${compose[@]}" ps
printf '\nDeploy selesai. Reverse proxy HTTPS di host dapat diarahkan ke 127.0.0.1:%s.\n' \
  "$(read_env_value PROXY_PORT | sed 's/^$/8080/')"
printf 'Jangan membuka port aplikasi 8000 atau proxy ini langsung ke internet tanpa TLS.\n'
