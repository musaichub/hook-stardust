#!/bin/sh
set -eu
STARDUST_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="$STARDUST_DIR/.venv/cache"
if [ ! -x "$STARDUST_DIR/.venv/bin/python" ]; then
    python3 -m venv "$STARDUST_DIR/.venv"
fi
if ! "$STARDUST_DIR/.venv/bin/python" -c 'import boto3' >/dev/null 2>&1; then
    "$STARDUST_DIR/.venv/bin/python" -m pip install -r "$STARDUST_DIR/requirements.txt"
fi
"$STARDUST_DIR/.venv/bin/python" "$STARDUST_DIR/source/build.py"
exec "$STARDUST_DIR/.venv/bin/python" "$STARDUST_DIR/server.py" "$@"
