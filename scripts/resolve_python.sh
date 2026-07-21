#!/bin/bash
# Print an absolute path to a Python interpreter that ACTUALLY EXECUTES PYTHON.
#
# We test the property (can it run code?), not the name. The Windows Store `python3`
# is a stub: it exists on PATH but prints "Python" and runs nothing, so a name or
# existence check picks a non-working interpreter and the demo dies with a misleading
# "Flask not found". Every candidate is probed the same way; any broken one — Store
# stub or otherwise — fails identically.
#
# Order: $PYTHON override -> the project venv (Unix or Windows layout) when it has
# flask -> py -3 (Windows Python Launcher, never the stub) -> python -> python3 ->
# a venv that runs but lacks flask (still fine for the zero-dep replay path).
# Prefers the venv setup.sh populated, so `bash setup.sh && bash start_demo.sh`
# needs no manual `source .venv/bin/activate`.
REPO="${REPO:-$(cd "$(dirname "$0")/.." && pwd)}"

# Valid only if `-c "print(1)"` prints exactly 1 (the stub prints "Python" and fails
# this; exit code alone is unreliable — some stubs exit 0).
_works() { [ "$("$@" -c 'print(1)' 2>/dev/null)" = "1" ]; }
# Canonicalize a working candidate to its real interpreter path, then exit. A single
# absolute path is quoting-safe (no multi-word `py -3` trap) and OS-agnostic.
_emit() {
    local p
    p="$("$@" -c 'import sys; print(sys.executable)' 2>/dev/null)"
    [ -n "$p" ] && { printf '%s\n' "$p"; exit 0; }
}

# 1. Explicit override — trust it as given.
if [ -n "$PYTHON" ]; then printf '%s\n' "$PYTHON"; exit 0; fi

# 2. Project venv (Unix bin/ and Windows Scripts/ layouts), preferred when set up.
for VENV_PY in "$REPO/.venv/bin/python" "$REPO/.venv/Scripts/python.exe"; do
    if [ -x "$VENV_PY" ] && _works "$VENV_PY" && "$VENV_PY" -c 'import flask' >/dev/null 2>&1; then
        _emit "$VENV_PY"
    fi
done

# 3. System interpreters — probed in order; the first that executes code wins.
for CAND in "py -3" python python3; do
    _works $CAND && _emit $CAND
done

# 4. A venv that runs Python but lacks flask is still a valid interpreter (the
#    replay path needs no deps) — prefer it over failing.
for VENV_PY in "$REPO/.venv/bin/python" "$REPO/.venv/Scripts/python.exe"; do
    [ -x "$VENV_PY" ] && _works "$VENV_PY" && _emit "$VENV_PY"
done

# 5. Nothing worked — emit a name so the caller fails loudly, not silently.
printf '%s\n' "python3"
