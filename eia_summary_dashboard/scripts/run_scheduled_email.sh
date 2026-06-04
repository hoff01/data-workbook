#!/bin/zsh
set -euo pipefail

ROOT="/Users/alexhoffmann/python_pulls/eia_summary_dashboard"
PYTHON="$ROOT/.venv/bin/python"
PATH="/usr/local/bin:/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:/usr/bin:/bin:/usr/sbin:/sbin"

timestamp() {
  date "+%Y-%m-%dT%H:%M:%S%z"
}

cd "$ROOT"
mkdir -p logs

{
  echo "[$(timestamp)] python=$PYTHON"
  echo "[$(timestamp)] starting DOE summary dashboard email"
  "$PYTHON" build.py --refresh-eia-latest --week latest --validate --send-email --email-mode smtp --email-mode mail
  echo "[$(timestamp)] completed DOE summary dashboard email"
} >> "$ROOT/logs/scheduled_email.log" 2>&1
