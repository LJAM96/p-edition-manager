#!/bin/bash
set -euo pipefail

CMD_FILE=/etc/edition-manager-command

if [ -f "$CMD_FILE" ]; then
  CMD="$(cat "$CMD_FILE")"
else
  CMD="python /app/edition-manager.py --all"
fi

exec runuser -u app -- sh -c "$CMD"