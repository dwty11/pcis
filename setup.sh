#!/bin/bash
set -e

echo "Setting up PCIS..."

HERE="$(cd "$(dirname "$0")" && pwd)"
# Resolve a working Python — stub-aware, so the Windows Store `python3` no-op stub
# never gets picked. No venv exists yet, so this returns a system interpreter.
PY="$(REPO="$HERE" bash "$HERE/scripts/resolve_python.sh")"

# Create the virtualenv if we're not already inside one.
if [ -z "${VIRTUAL_ENV:-}" ]; then
    "$PY" -m venv .venv
    echo "Virtual environment created at .venv"
fi

# Use the venv interpreter directly (Unix bin/ or Windows Scripts/) — no
# `source .venv/bin/activate`, which differs by OS and breaks under Git Bash.
VENV_PY="$HERE/.venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="$HERE/.venv/Scripts/python.exe"
[ -x "$VENV_PY" ] || VENV_PY="$PY"   # already inside a venv, or venv creation skipped

"$VENV_PY" -m pip install -r requirements.txt
# Install the package so the `pcis` command exists (console script in .venv/bin).
"$VENV_PY" -m pip install -e . --quiet
mkdir -p data
cp demo/demo_tree.json data/tree.json
echo '[]' > data/belief-history.json

# Pre-pull the embedding model so first semantic search doesn't silently fail
if command -v ollama &>/dev/null; then
    echo "Pulling nomic-embed-text embedding model..."
    ollama pull nomic-embed-text
else
    echo "Warning: ollama not found — semantic search will be unavailable."
    echo "Install from https://ollama.com then run: ollama pull nomic-embed-text"
fi

echo ""
echo "Setup complete."
echo "To run the Advocate demo:      ./run_demo.sh"
echo "To run the server demo:        bash start_demo.sh"
echo "To challenge your own claims:  source .venv/bin/activate, then 'pcis init' (see README)"
