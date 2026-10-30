#!/bin/bash
# Telur Finance - Backup Script
# Usage: ./scripts/backup.sh [daily|weekly|monthly]

set -euo pipefail

BACKUP_TYPE="${1:-daily}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="/backup"
PROJECT_NAME="telur-finance"
DB_NAME="${POSTGRES_DB:-telur_finance}"
DB_USER="${POSTGRES_USER:-telur}"
DB_HOST="${POSTGRES_HOST:-db}"

case "$BACKUP_TYPE" in
    daily) RETENTION_DAYS=7 ;;
    weekly) RETENTION_DAYS=30 ;;
    monthly) RETENTION_DAYS=365 ;;
    *) echo "Usage: $0 [daily|weekly|monthly]"; exit 1 ;;
esac

echo "[$(date)] Starting $BACKUP_TYPE backup..."

# Database backup
DB_FILE="${BACKUP_DIR}/${PROJECT_NAME}_${BACKUP_TYPE}_${TIMESTAMP}.sql.gz"
echo "[$(date)] Dumping database to $DB_FILE..."
docker compose -f docker-compose.prod.yml exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME" | gzip > "$DB_FILE"

if [ ${PIPESTATUS[0]} -ne 0 ]; then
    echo "[$(date)] ERROR: Database dump failed!"
    rm -f "$DB_FILE"
    exit 1
fi

# Media files backup
MEDIA_FILE="${BACKUP_DIR}/${PROJECT_NAME}_${BACKUP_TYPE}_media_${TIMESTAMP}.tar.gz"
echo "[$(date)] Archiving media files to $MEDIA_FILE..."
docker compose -f docker-compose.prod.yml exec -T app tar -czf - -C /media . > "$MEDIA_FILE" 2>/dev/null || true

# Verify backups
DB_SIZE=$(stat -c%s "$DB_FILE")
MEDIA_SIZE=$(stat -c%s "$MEDIA_FILE")
echo "[$(date)] Database backup: $(numfmt --to=iec $DB_SIZE)"
echo "[$(date)] Media backup: $(numfmt --to=iec $MEDIA_SIZE)"

# Cleanup old backups
echo "[$(date)] Cleaning up backups older than $RETENTION_DAYS days..."
find "$BACKUP_DIR" -name "${PROJECT_NAME}_${BACKUP_TYPE}_*" -type f -mtime +$RETENTION_DAYS -delete

echo "[$(date)] $BACKUP_TYPE backup completed successfully!"
echo "[$(date)] Database: $DB_FILE"
echo "[$(date)] Media: $MEDIA_FILE"