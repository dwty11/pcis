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
echo ""
echo "Setup complete."
echo "To activate: source .venv/bin/activate"
echo "To run:      python demo/server.py"
