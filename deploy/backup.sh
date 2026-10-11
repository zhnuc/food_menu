#!/usr/bin/env bash
# Private paired DB/image/media backup. Keep this folder off the web root.
set -euo pipefail
umask 077
cd /opt/together-kitchen
task_backup_dir=/opt/together-kitchen-private/backups
mkdir -p "$task_backup_dir"
task_stamp=$(date -u +%Y%m%dT%H%M%SZ)
task_work=$(mktemp -d "$task_backup_dir/.backup-XXXXXX")
task_compose=(docker compose --env-file deploy/production.env -f deploy/compose.yaml -f deploy/small-server.yaml)
if [[ -f deploy/gateway.yaml && -d /opt/together-kitchen-private/gateway-configs ]]; then
    task_compose+=(-f deploy/gateway.yaml)
fi
task_resume() { "${task_compose[@]}" up -d --no-build api worker https; }
trap task_resume EXIT
# Stop writers, retain PostgreSQL and every persistent volume.
"${task_compose[@]}" stop api worker
"${task_compose[@]}" run --rm --no-deps -v "$task_work:/private-backup" --user root api \
    python database_tools.py backup /private-backup/database.zip
"${task_compose[@]}" run --rm --no-deps -v "$task_work:/private-backup" --user root api \
    tar -C /app -czf /private-backup/media.tar.gz data
if [[ -d /opt/together-kitchen-private/gateway-configs ]]; then
    tar -C /opt/together-kitchen-private -czf "$task_work/gateway-configs.tar.gz" gateway-configs
fi
mv "$task_work" "$task_backup_dir/$task_stamp"
echo "Private backup completed: $task_stamp"
