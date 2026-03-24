#!/bin/bash
set -e

echo "Setting up PCIS..."

# Create and activate a virtual environment if not already inside one
if [ -z "$VIRTUAL_ENV" ]; then
    python3 -m venv .venv
    source .venv/bin/activate
    echo "Virtual environment created at .venv"
fi

pip install -r requirements.txt
mkdir -p data
cp demo/demo_tree.json data/tree.json

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
echo "To activate: source .venv/bin/activate"
echo "To run:      python demo/server.py"
