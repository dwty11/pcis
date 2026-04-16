#!/bin/bash
# PCIS Demo Startup Script
# Boots all required components for the Thursday demo.
# Run from repo root: ./start_demo.sh

REPO="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-python3}"
FAILED=0

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║        PCIS Demo Startup             ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# ── 1. Verify repo root ────────────────────────────────────────────────────
if [ ! -f "$REPO/demo/server.py" ]; then
  echo "  ✗  Run this script from the repo root: ./start_demo.sh"
  exit 1
fi

# ── 2. Check dependencies ─────────────────────────────────────────────────
echo "  [1/5] Checking Python dependencies..."
if ! $PYTHON -c "import flask" 2>/dev/null; then
  echo "  ✗  Flask not found. Run: pip install flask"
  exit 1
fi
echo "  ✓  Flask OK"

# ── 3. Verify demo tree integrity ─────────────────────────────────────────
echo "  [2/5] Verifying demo tree integrity..."
INTEGRITY=$($PYTHON -c "
import sys, json
sys.path.insert(0, '$REPO/core')
sys.path.insert(0, '$REPO')
from core.knowledge_tree import verify_tree_integrity
with open('$REPO/demo/demo_tree.json') as f:
    tree = json.load(f)
ok, errors = verify_tree_integrity(tree)
print('OK' if ok else 'FAIL')
" 2>&1)

if [ "$INTEGRITY" = "OK" ]; then
  echo "  ✓  demo_tree.json: CLEAN"
else
  echo "  ✗  demo_tree.json integrity FAILED"
  FAILED=1
fi

# ── 4. External validator check (optional) ────────────────────────────────
echo "  [3/5] Checking External validator (localhost:7860)..."
GIGACHAT_STATUS=$(curl -s --max-time 2 http://localhost:7860/health 2>/dev/null)
if echo "$GIGACHAT_STATUS" | grep -q '"status":"ok"'; then
  echo "  ✓  External validator: RUNNING"
else
  echo "  ⚠  External validator not running on localhost:7860"
  echo "     Start it before demo: External Validation tab will fail without it"
fi

# ── 5. Run test suite ───────────────────────────────────────────────────────
echo "  [4/5] Running test suite..."
TEST_OUTPUT=$($PYTHON -m pytest "$REPO/tests/" -q 2>&1)
TEST_EXIT=$?
if [ $TEST_EXIT -eq 0 ]; then
  PASS_COUNT=$(echo "$TEST_OUTPUT" | grep -o '[0-9]* passed' | head -1)
  echo "  ✓  Tests: $PASS_COUNT"
else
  echo "  ✗  Tests failed — fix before demo"
  echo "$TEST_OUTPUT" | tail -10
  FAILED=1
fi

if [ $FAILED -ne 0 ]; then
  echo ""
  echo "  ✗  Pre-flight checks failed. Fix above before continuing."
  exit 1
fi

# ── 6. Start Flask demo server ────────────────────────────────────────────
echo "  [5/5] Starting demo server..."

# Kill any existing demo server on 5555
EXISTING=$(/usr/sbin/lsof -ti:5555 2>/dev/null)
if [ -n "$EXISTING" ]; then
  echo "  ↺  Stopping existing process on :5555 (pid $EXISTING)..."
  kill "$EXISTING" 2>/dev/null || true
  sleep 1
fi

LOG="$REPO/demo/server.log"
cd "$REPO/demo"
$PYTHON server.py > "$LOG" 2>&1 &
SERVER_PID=$!

# Wait for server to be ready (up to 8s)
for i in 1 2 3 4; do
  sleep 2
  BOOT_STATUS=$(curl -s --max-time 3 http://localhost:5555/api/boot 2>/dev/null)
  if [ -n "$BOOT_STATUS" ]; then
    break
  fi
done

if echo "$BOOT_STATUS" | grep -q '"CLEAN"'; then
  echo "  ✓  Demo server: RUNNING (pid $SERVER_PID)"
elif [ -n "$BOOT_STATUS" ]; then
  echo "  ⚠  Demo server running — integrity not CLEAN, check /api/boot"
else
  echo "  ✗  Demo server did not respond. Log:"
  tail -5 "$LOG"
  exit 1
fi

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║  READY  →  http://localhost:5555     ║"
echo "  ╚══════════════════════════════════════╝"
echo ""
echo "  Log:  $LOG"
echo "  Stop: kill $SERVER_PID"
echo ""
