#!/usr/bin/env bash
# The Advocate Demo. Default mode --replay: a locked, recorded REAL gardener run,
# zero external dependencies (Python stdlib + shipped fixtures), < 60s on any machine.
#   --live         run the shipped gardener fresh on your own local model
#   --verify-self  SHA-256 every script + fixture vs CANONICAL_FINGERPRINT.txt
# Everything runs on your machine. The public gardener is Ollama/MLX only — nothing
# leaves it; --replay needs no model at all.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
PY="$(REPO="$REPO" bash "$REPO/scripts/resolve_python.sh")"
export PYTHONPATH="$REPO/core:$REPO:${PYTHONPATH:-}"
export PCIS_BASE_DIR="$HERE/fixtures/base"
export PCIS_TREE_FILE="$HERE/fixtures/seed_tree.json"

case "${1:-}" in
  --verify-self) exec "$PY" "$HERE/verify_self.py" ;;
  --live)
    # Default --live to the model the recording used (canonical_run.json's `model`),
    # so replay and live agree out of the box. A user's own PCIS_GARDENER_MODEL wins.
    export PCIS_GARDENER_MODEL="${PCIS_GARDENER_MODEL:-$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["model"])' "$HERE/fixtures/canonical_run.json")}"
    exec "$PY" "$HERE/replay.py" --live ;;
  --replay|"")   exec "$PY" "$HERE/replay.py" ;;
  -h|--help)     echo "usage: run_demo.sh [--replay | --live | --verify-self]"; exit 0 ;;
  *) echo "unknown option: $1"; echo "usage: run_demo.sh [--replay | --live | --verify-self]"; exit 2 ;;
esac
