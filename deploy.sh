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

for key in DJANGO_SECRET_KEY DJANGO_ALLOWED_HOSTS POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD POSTGRES_HOST; do
  value="$(read_env_value "$key")"
  [[ -n "$value" ]] || fail "$key wajib diisi di .env."
done

secret_key="$(read_env_value DJANGO_SECRET_KEY)"
db_password="$(read_env_value POSTGRES_PASSWORD)"
allowed_hosts="$(read_env_value DJANGO_ALLOWED_HOSTS)"
[[ ${#secret_key} -ge 50 && "$secret_key" != REPLACE_* ]] || fail "DJANGO_SECRET_KEY harus berupa secret acak minimal 50 karakter."
[[ "$allowed_hosts" != *"*"* ]] || fail "DJANGO_ALLOWED_HOSTS tidak boleh menggunakan wildcard (*)."

if [[ -e "$ROOT_DIR/.git" ]]; then
  command -v git >/dev/null 2>&1 || fail "Git tidak tersedia untuk memperbarui checkout ini."
  git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || fail "direktori .git ada tetapi checkout Git tidak valid."
  branch="$(git -C "$ROOT_DIR" branch --show-current)"
  [[ "$branch" == main ]] || fail "branch aktif harus main, saat ini: ${branch:-detached HEAD}."
  if [[ -n "$(git -C "$ROOT_DIR" status --porcelain --untracked-files=normal)" ]]; then
    fail "worktree memiliki perubahan lokal. Commit atau simpan perubahan sebelum deploy."
  fi
  git -C "$ROOT_DIR" pull --ff-only origin main
else
  printf 'Direktori ini bukan checkout Git; deploy memakai source yang sudah ada (tanpa git pull).\n'
fi

cd "$ROOT_DIR"
compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
"${compose[@]}" config --quiet
command -v pg_dump >/dev/null 2>&1 || fail "pg_dump belum terpasang; pasang postgresql-client untuk backup PostgreSQL host."
mkdir -p "$ROOT_DIR/backups"
chmod 700 "$ROOT_DIR/backups"

backup_file="$ROOT_DIR/backups/telur-finance-$(date +%Y%m%d-%H%M%S).dump"
backup_host="$(read_env_value POSTGRES_BACKUP_HOST)"
backup_port="$(read_env_value POSTGRES_PORT)"
[[ -n "$backup_host" ]] || backup_host=127.0.0.1
[[ -n "$backup_port" ]] || backup_port=5432
printf 'Membuat backup database PostgreSQL sebelum deploy...\n'
if ! PGPASSWORD="$db_password" pg_dump \
  --host="$backup_host" \
  --port="$backup_port" \
  --username="$(read_env_value POSTGRES_USER)" \
  --dbname="$(read_env_value POSTGRES_DB)" \
  --format=custom >"$backup_file"; then
  rm -f "$backup_file"
  fail "backup database gagal; service tidak diperbarui."
fi
chmod 600 "$backup_file"
printf 'Backup tersimpan di backups/%s\n' "$(basename "$backup_file")"

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

printf 'Menunggu health check app...\n'
wait_for_health app

caddy_container=""
caddy_status=""
for ((attempt = 1; attempt <= 60; attempt++)); do
  caddy_container="$("${compose[@]}" ps -q caddy)"
  if [[ -n "$caddy_container" ]]; then
    caddy_status="$(docker inspect -f '{{.State.Status}}' "$caddy_container")"
    [[ "$caddy_status" == running ]] && break
    if [[ "$caddy_status" == exited || "$caddy_status" == dead ]]; then
      "${compose[@]}" logs --tail=80 caddy >&2
      fail "service caddy berstatus $caddy_status."
    fi
  fi
  sleep 2
done
[[ -n "$caddy_container" && "$caddy_status" == running ]] || fail "service caddy belum berjalan setelah 120 detik."

"${compose[@]}" ps
printf '\nDeploy selesai. Caddy menangani HTTPS pada port 80/443.\n'
