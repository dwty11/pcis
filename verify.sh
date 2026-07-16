#!/usr/bin/env bash
# verify.sh — verify the PCIS knowledge chain, end to end.
#
# Re-derives every leaf hash from its CONTENT (not the cached hashes),
# recomputes the Merkle root, and reports whether the record is untampered.
# A thin wrapper over `pcis verify` + `pcis root` — the real content check:
# a one-byte edit to any leaf flips the status to TAMPERED.
#
# Usage:
#   bash setup.sh     # one-time: initialize data/tree.json
#   ./verify.sh       # verify it
#
# Honors PCIS_BASE_DIR (default: this repo root).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="${PCIS_BASE_DIR:-$HERE}"
TREE="$BASE/data/tree.json"

if [ ! -f "$TREE" ]; then
  echo "No tree at $TREE — run 'bash setup.sh' first to initialize one." >&2
  exit 2
fi

# Full content-integrity check (re-derives per-leaf hashes; exit 0 = CLEAN, 1 = TAMPERED).
out="$(python3 -m pcis.cli --dir "$BASE" verify 2>&1)"; rc=$?
root="$(python3 -m pcis.cli --dir "$BASE" root 2>/dev/null)"
leaves="$(python3 - "$TREE" <<'PY'
import json, sys
tree = json.load(open(sys.argv[1]))
print(sum(len(b.get("leaves", [])) for b in tree.get("branches", {}).values()))
PY
)"

echo "Chain root: ${root:0:16}..."
echo "Leaves:     $leaves"
if [ "$rc" -eq 0 ]; then
  echo "Status:     ✓ Untampered"
else
  echo "Status:     ✗ TAMPERED"
  echo "$out" | sed 's/^/            /'
fi
exit "$rc"
