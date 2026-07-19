#!/bin/bash
# Print the Python interpreter the demo scripts should use.
#
# Prefers the project virtualenv that setup.sh populates, so
# `bash setup.sh && bash start_demo.sh` works with no manual
# `source .venv/bin/activate`. Falls back to system python3 when the venv is
# absent or can't import flask (e.g. a stale venv), and honors an explicit
# $PYTHON override.
REPO="${REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
VENV_PY="$REPO/.venv/bin/python"

if [ -n "$PYTHON" ]; then
    echo "$PYTHON"
elif [ -x "$VENV_PY" ] && "$VENV_PY" -c "import flask" >/dev/null 2>&1; then
    echo "$VENV_PY"
else
    echo "python3"
fi
