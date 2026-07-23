#!/bin/bash
# PCIS Demo Startup Script
# Boots all required components for the PCIS demo.
# Run from repo root: ./start_demo.sh

REPO="$(cd "$(dirname "$0")" && pwd)"
# Prefer the venv setup.sh populated (falls back to system python3); no manual
# `source .venv/bin/activate` needed for `bash setup.sh && bash start_demo.sh`.
PYTHON="$(REPO="$REPO" bash "$REPO/scripts/resolve_python.sh")"
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

# ── 2. Check dependencies (auto-bootstrap via setup.sh if missing) ─────────
echo "  [1/5] Checking Python dependencies..."
if ! "$PYTHON" -c "import flask" 2>/dev/null; then
  echo "  ○  Flask not found — bootstrapping with 'bash setup.sh'..."
  bash "$REPO/setup.sh" || true
  # setup.sh creates the venv; re-resolve so we pick it up.
  PYTHON="$(REPO="$REPO" bash "$REPO/scripts/resolve_python.sh")"
  if ! "$PYTHON" -c "import flask" 2>/dev/null; then
    echo "  ✗  Flask still missing after setup. Run 'bash setup.sh' and check its output."
    exit 1
  fi
fi
echo "  ✓  Flask OK"

# ── 3. Verify demo tree integrity ─────────────────────────────────────────
echo "  [2/5] Verifying demo tree integrity..."
# Relative paths, run from inside $REPO (see the capture below). On Git Bash/MINGW64, $REPO is a
# bash-form drive path (/c/<home>/...); MSYS converts paths passed as ARGUMENTS to a native Windows Python
# but NOT paths embedded in a `-c` string, so an absolute '$REPO/...' here would reach Python as an
# unresolvable /c/... path. `cd "$REPO"` + relative paths is what step 4 already does.
_STEP2_PY="import sys, json
sys.path.insert(0, 'core')
sys.path.insert(0, '.')
from core.knowledge_tree import verify_tree_integrity
with open('demo/demo_tree.json', encoding='utf-8') as f:
    tree = json.load(f)
ok, errors = verify_tree_integrity(tree)
print('OK' if ok else 'FAIL')
if errors:
    sys.stderr.write('integrity errors: ' + '; '.join(str(e) for e in errors[:5]) + '\n')"

# Capture stdout and stderr SEPARATELY: the verdict compares only stdout, and PCIS_DEBUG shows
# the inline python's stderr rather than swallowing it (2>&1 used to merge them, hiding errors).
_STEP2_ERR="$(mktemp 2>/dev/null || echo "${TMPDIR:-/tmp}/pcis_step2_err.$$")"
INTEGRITY_RAW="$(cd "$REPO" && "$PYTHON" -c "$_STEP2_PY" 2>"$_STEP2_ERR")"
INTEGRITY="${INTEGRITY_RAW//$'\r'/}"   # native-Windows Python prints CRLF, so $() yields "OK\r"; strip CR or the exact compare below false-fails

# PCIS_DEBUG=1 bash start_demo.sh -> print the actual captured bytes (od -c makes CR/whitespace visible).
if [ -n "${PCIS_DEBUG:-}" ]; then
  {
    echo "  ---- PCIS_DEBUG · step 2 ----"
    echo "  \$PYTHON               : $PYTHON"
    echo "  \$REPO                 : $REPO"
    echo "  command               : \"\$PYTHON\" -c \"<step-2 integrity check>\"  (stderr -> temp file)"
    echo "  raw stdout   (od -c)  :"; printf '%s' "$INTEGRITY_RAW" | od -c | sed 's/^/      /'
    echo "  after CR-strip(od -c) :"; printf '%s' "$INTEGRITY"     | od -c | sed 's/^/      /'
    echo "  inline-python stderr  :"; sed 's/^/      /' "$_STEP2_ERR" 2>/dev/null; [ -s "$_STEP2_ERR" ] || echo "      (empty)"
    if [ "$INTEGRITY" = "OK" ]; then _CMP="EQUAL  -> CLEAN"; else _CMP="NOT EQUAL  -> FAILED"; fi
    echo "  compare [ \"\$INTEGRITY\" = \"OK\" ] : $_CMP"
    echo "  -----------------------------"
  } >&2
fi
rm -f "$_STEP2_ERR"

if [ "$INTEGRITY" = "OK" ]; then
  echo "  ✓  demo_tree.json: CLEAN"
else
  echo "  ✗  demo_tree.json integrity FAILED"
  FAILED=1
fi

# ── 4. External validator check (optional, bring-your-own) ────────────────
echo "  [3/5] Checking External validator (optional, localhost:7860)..."
EXT_STATUS=$(curl -s --max-time 2 http://localhost:7860/health 2>/dev/null)
if echo "$EXT_STATUS" | grep -q '"status":"ok"'; then
  echo "  ✓  External validator: RUNNING"
else
  echo "  ○  External validator not detected — optional. Only the 'External"
  echo "     Validation' tab needs it: bring your own OpenAI-compatible adapter"
  echo "     on :7860 (see README). The rest of the demo works without it."
fi

# ── 5. Smoke check (fast — the full suite is 'pytest tests/', not a boot gate) ──
echo "  [4/5] Smoke check (server imports)..."
if ( cd "$REPO" && $PYTHON -c "import sys; sys.path.insert(0,'demo'); import server" >/dev/null 2>&1 ); then
  echo "  ✓  Server imports clean"
else
  echo "  ⚠  Server import smoke failed — it may not boot. Run: $PYTHON -m pytest tests/"
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
