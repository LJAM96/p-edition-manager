#!/bin/bash
set -euo pipefail

MODE="${EDITION_MANAGER_MODE:-cli}"

if [ "$MODE" = "cron" ]; then
  CRON_SCHEDULE="${CRON_SCHEDULE:-0 */4 * * *}"
  CRON_COMMAND="${CRON_COMMAND:-python /app/edition-manager.py --all}"
  CRON_COMMAND_FILE=/etc/edition-manager-command

  echo "$CRON_COMMAND" > "$CRON_COMMAND_FILE"
  chmod 0644 "$CRON_COMMAND_FILE"

  cat <<EOF >/etc/cron.d/edition-manager
$CRON_SCHEDULE root /usr/local/bin/edition-manager-cron.sh
EOF
  chmod 0644 /etc/cron.d/edition-manager

  exec cron -f
else
  exec "$@"
fi
