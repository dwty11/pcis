#!/bin/bash
set -e

echo "Setting up PCIS..."

HERE="$(cd "$(dirname "$0")" && pwd)"
# Resolve a Python that meets the 3.10+ floor the editable install needs (a modern pip,
# to install a pyproject-only package). PCIS_MIN_PY makes the stub-aware resolver
# version-aware too: on macOS /usr/bin/python3 is 3.9, and building a venv on it installs
# requirements and then dies at `pip install -e .` — leaving a half-built venv and no
# data/. On failure the resolver prints exactly how to fix it (a PYTHON= override);
# surface that and stop — never build a venv we can't finish.
if ! PY="$(PCIS_MIN_PY=3.10 REPO="$HERE" bash "$HERE/scripts/resolve_python.sh")"; then
    exit 1
fi

VENV="$HERE/.venv"
# Create the venv, or recreate it if an existing one is a DIFFERENT Python — a half-built
# 3.9 venv from a prior run is sticky (the resolver prefers a populated venv), so `--clear`
# guarantees a clean one on the interpreter we just vetted.
if [ -z "${VIRTUAL_ENV:-}" ]; then
    WANT="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    EXIST_PY="$VENV/bin/python"; [ -x "$EXIST_PY" ] || EXIST_PY="$VENV/Scripts/python.exe"
    if [ -x "$EXIST_PY" ]; then
        HAVE="$("$EXIST_PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "")"
        if [ "$HAVE" != "$WANT" ]; then
            echo "Existing .venv is Python ${HAVE:-unusable} — need $WANT; recreating (--clear)."
            "$PY" -m venv --clear "$VENV"
        fi
    else
        "$PY" -m venv "$VENV"
    fi
    echo "Virtual environment ready at .venv (Python $WANT)"
fi

# Use the venv interpreter directly (Unix bin/ or Windows Scripts/) — no
# `source .venv/bin/activate`, which differs by OS and breaks under Git Bash.
VENV_PY="$VENV/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="$VENV/Scripts/python.exe"
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
# Print the activate path that actually exists on this OS (Unix bin/, Windows Scripts/).
ACT="$VENV/bin/activate"; [ -f "$ACT" ] || ACT="$VENV/Scripts/activate"
echo "Setup complete."
echo "To run the Advocate demo:      ./run_demo.sh"
echo "To run the server demo:        bash start_demo.sh"
echo "To challenge your own claims:  source ${ACT#$HERE/}, then 'export PCIS_BASE_DIR=~/my-pcis' and 'pcis init' (see README)"
