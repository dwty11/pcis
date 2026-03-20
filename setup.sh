#!/bin/bash
set -e

echo "Setting up PCIS..."
pip install -r requirements.txt
mkdir -p data
cp demo/demo_tree.json data/tree.json
echo ""
echo "Setup complete. Run: python demo/server.py"
