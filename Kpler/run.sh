#!/usr/bin/env bash
set -euo pipefail

KPLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$KPLER_DIR/.." && pwd)"
VENV="$KPLER_DIR/.venv"
PYTHON="$VENV/bin/python"
LOCAL_ENV="$KPLER_DIR/config/local.env"

load_local_env() {
  if [[ -f "$LOCAL_ENV" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$LOCAL_ENV"
    set +a
  fi
}

setup() {
  if [[ ! -x "$PYTHON" ]]; then
    python3 -m venv "$VENV"
  fi
  "$PYTHON" -m pip install --upgrade pip
  "$PYTHON" -m pip install -r "$KPLER_DIR/requirements.txt"
}

case "${1:-setup-preflight}" in
  setup)
    setup
    ;;
  preflight)
    if [[ ! -x "$PYTHON" ]]; then
      setup
    fi
    load_local_env
    "$PYTHON" "$REPO_DIR/src/kpler_pull.py" --preflight
    ;;
  auth-check)
    if [[ ! -x "$PYTHON" ]]; then
      setup
    fi
    load_local_env
    "$PYTHON" "$REPO_DIR/src/kpler_pull.py" --check-auth
    ;;
  run)
    if [[ ! -x "$PYTHON" ]]; then
      setup
    fi
    load_local_env
    "$PYTHON" "$REPO_DIR/src/kpler_pull.py"
    ;;
  setup-preflight)
    setup
    load_local_env
    "$PYTHON" "$REPO_DIR/src/kpler_pull.py" --preflight
    ;;
  *)
    echo "Usage: ./run.sh [setup|preflight|auth-check|run|setup-preflight]" >&2
    exit 1
    ;;
esac
