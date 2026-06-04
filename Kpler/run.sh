#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT_DIR/.venv"
PYTHON="$VENV/bin/python"

setup() {
  if [[ ! -x "$PYTHON" ]]; then
    python3 -m venv "$VENV"
  fi
  "$PYTHON" -m pip install --upgrade pip
  "$PYTHON" -m pip install -r "$ROOT_DIR/requirements.txt"
}

case "${1:-setup-preflight}" in
  setup)
    setup
    ;;
  preflight)
    if [[ ! -x "$PYTHON" ]]; then
      setup
    fi
    "$PYTHON" "$ROOT_DIR/src/kpler_pull.py" --preflight
    ;;
  run)
    if [[ ! -x "$PYTHON" ]]; then
      setup
    fi
    "$PYTHON" "$ROOT_DIR/src/kpler_pull.py"
    ;;
  setup-preflight)
    setup
    "$PYTHON" "$ROOT_DIR/src/kpler_pull.py" --preflight
    ;;
  *)
    echo "Usage: ./run.sh [setup|preflight|run|setup-preflight]" >&2
    exit 1
    ;;
esac
