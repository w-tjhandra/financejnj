#!/bin/bash
# Telur Finance - Restore Script
# Usage: ./scripts/restore.sh <backup_file.sql.gz> [media_file.tar.gz]

set -euo pipefail

DB_FILE="${1:-}"
MEDIA_FILE="${2:-}"
DB_NAME="${POSTGRES_DB:-telur_finance}"
DB_USER="${POSTGRES_USER:-telur}"
DB_HOST="${POSTGRES_HOST:-db}"

if [ -z "$DB_FILE" ]; then
    echo "Usage: $0 <backup_file.sql.gz> [media_file.tar.gz]"
    echo "Example: $0 /backup/telur-finance_daily_20260115_020000.sql.gz /backup/telur-finance_daily_media_20260115_020000.tar.gz"
    exit 1
fi

if [ ! -f "$DB_FILE" ]; then
    echo "ERROR: Database backup file not found: $DB_FILE"
    exit 1
fi

echo "[$(date)] Starting restore from $DB_FILE..."

# Confirm restore
read -p "This will REPLACE the current database. Continue? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Restore cancelled."
    exit 1
fi

# Stop app to prevent connections during restore
echo "[$(date)] Stopping application..."
docker compose -f docker-compose.prod.yml stop app

# Restore database
echo "[$(date)] Restoring database from $DB_FILE..."
gunzip -c "$DB_FILE" | docker compose -f docker-compose.prod.yml exec -T db psql -U "$DB_USER" -d "$DB_NAME"

if [ ${PIPESTATUS[0]} -ne 0 ]; then
    echo "[$(date)] ERROR: Database restore failed!"
    docker compose -f docker-compose.prod.yml start app
    exit 1
fi

# Restore media files if provided
if [ -n "$MEDIA_FILE" ] && [ -f "$MEDIA_FILE" ]; then
    echo "[$(date)] Restoring media files from $MEDIA_FILE..."
    docker compose -f docker-compose.prod.yml exec -T app tar -xzf - -C /media < "$MEDIA_FILE"
fi

# Run migrations in case of schema changes
echo "[$(date)] Running migrations..."
docker compose -f docker-compose.prod.yml exec -T app python manage.py migrate --noinput

# Restart app
echo "[$(date)] Starting application..."
docker compose -f docker-compose.prod.yml start app

echo "[$(date)] Restore completed successfully!"
echo "[$(date)] Database restored from: $DB_FILE"
[ -n "$MEDIA_FILE" ] && echo "[$(date)] Media restored from: $MEDIA_FILE"