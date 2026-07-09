#!/bin/zsh
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROUTE="${1:-/}"
LOCAL_ROOT="${US_BALANCES_RUNTIME_ROOT:-$HOME/US_Balances}"
NODE_ROOT="$LOCAL_ROOT/node"
PYTHON_ROOT="$LOCAL_ROOT/python"
CACHE_ROOT="$LOCAL_ROOT/cache"
mkdir -p "$NODE_ROOT" "$PYTHON_ROOT" "$CACHE_ROOT/npm" "$CACHE_ROOT/pip" "$CACHE_ROOT/pycache" "$CACHE_ROOT/matplotlib"

cp "$SCRIPT_DIR/package.json" "$NODE_ROOT/package.json"
if [[ -f "$SCRIPT_DIR/package-lock.json" ]]; then
  cp "$SCRIPT_DIR/package-lock.json" "$NODE_ROOT/package-lock.json"
fi

TSX="$NODE_ROOT/node_modules/.bin/tsx"
NODE_STAMP="$NODE_ROOT/.package-lock.sha256"
NODE_HASH="$(shasum -a 256 "$SCRIPT_DIR/package.json" "$SCRIPT_DIR/package-lock.json" 2>/dev/null | shasum -a 256 | awk '{print $1}')"
if [[ ! -x "$TSX" || ! -f "$NODE_STAMP" || "$(cat "$NODE_STAMP")" != "$NODE_HASH" ]]; then
  (cd "$NODE_ROOT" && { [[ -f package-lock.json ]] && npm ci || npm install; })
  printf '%s\n' "$NODE_HASH" > "$NODE_STAMP"
fi

PYTHON="$PYTHON_ROOT/.venv/bin/python"
PYTHON_STAMP="$PYTHON_ROOT/.requirements.sha256"
PYTHON_HASH="$(shasum -a 256 "$SCRIPT_DIR/requirements.txt" | awk '{print $1}')"
if [[ ! -x "$PYTHON" ]]; then
  python3 -m venv "$PYTHON_ROOT/.venv"
fi
if [[ ! -f "$PYTHON_STAMP" || "$(cat "$PYTHON_STAMP")" != "$PYTHON_HASH" ]]; then
  "$PYTHON" -m pip install --upgrade pip
  "$PYTHON" -m pip install -r "$SCRIPT_DIR/requirements.txt"
  printf '%s\n' "$PYTHON_HASH" > "$PYTHON_STAMP"
fi

cd "$SCRIPT_DIR"
US_BALANCES_SHARED_ROOT="$SCRIPT_DIR" \
US_BALANCES_RUNTIME_ROOT="$LOCAL_ROOT" \
US_BALANCES_TSX_COMMAND="$TSX" \
US_BALANCES_PYTHON="$PYTHON" \
npm_config_cache="$CACHE_ROOT/npm" \
PIP_CACHE_DIR="$CACHE_ROOT/pip" \
PYTHONPYCACHEPREFIX="$CACHE_ROOT/pycache" \
MPLCONFIGDIR="$CACHE_ROOT/matplotlib" \
"$TSX" "$SCRIPT_DIR/src/open_dashboard.ts" "$ROUTE"
