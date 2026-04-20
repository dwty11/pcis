#!/bin/bash
set -e

# Copy demo tree to working path (demo_tree.json is read-only source)
WORK_TREE="/app/data/tree.json"
mkdir -p /app/data

if [ ! -f "$WORK_TREE" ]; then
    cp /app/demo/demo_tree.json "$WORK_TREE"
    echo "[entrypoint] Seeded working tree from demo_tree.json"
fi

# Wait for Ollama to be ready (if OLLAMA_HOST is set)
if [ -n "$OLLAMA_HOST" ]; then
    echo "[entrypoint] Waiting for Ollama at $OLLAMA_HOST ..."
    for i in $(seq 1 30); do
        if curl -sf "$OLLAMA_HOST/api/tags" > /dev/null 2>&1; then
            echo "[entrypoint] Ollama is ready."
            break
        fi
        sleep 2
    done
fi

# Start Flask
exec python demo/server.py --host 0.0.0.0
