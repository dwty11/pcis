#!/bin/bash
# Print an absolute path to a Python interpreter that ACTUALLY EXECUTES PYTHON.
#
# We test the property (can it run code?), not the name. The Windows Store `python3`
# is a stub: it exists on PATH but prints "Python" and runs nothing, so a name or
# existence check picks a non-working interpreter and the demo dies with a misleading
# "Flask not found". Every candidate is probed the same way; any broken one — Store
# stub or otherwise — fails identically.
#
# Version floor: when PCIS_MIN_PY is set (e.g. "3.10"), a candidate must ALSO be at
# least that version, and if nothing qualifies the resolver fails LOUD — naming the
# PYTHON= override — instead of returning an interpreter the caller can't finish with.
# setup.sh sets it (the editable install needs a modern pip / Python 3.10+, and macOS
# ships 3.9 as /usr/bin/python3 — the same class of trap as the Windows stub, one
# version older). run_demo.sh's zero-dep replay leaves it unset, so an older-but-
# working interpreter is still fine there.
#
# Order: $PYTHON override -> the project venv (Unix or Windows layout) when it has
# flask -> py -3 (Windows Python Launcher, never the stub) -> python -> python3 ->
# a venv that runs but lacks flask (still fine for the zero-dep replay path).
# Prefers the venv setup.sh populated.
REPO="${REPO:-$(cd "$(dirname "$0")/.." && pwd)}"

# Valid only if `-c "print(1)"` prints exactly 1 (the stub prints "Python" and fails
# this; exit code alone is unreliable — some stubs exit 0).
_works() { [ "$("$@" -c 'print(1)' 2>/dev/null)" = "1" ]; }

# When PCIS_MIN_PY is set, the candidate must be at least that (major, minor). Unset =
# no floor (the replay path). Never a lexical compare — 3.9 vs 3.10 is a numeric tuple.
_meets_min() {
    [ -z "${PCIS_MIN_PY:-}" ] && return 0
    "$@" -c "import sys; mn=tuple(int(x) for x in '${PCIS_MIN_PY}'.split('.')); sys.exit(0 if sys.version_info[:len(mn)] >= mn else 1)" 2>/dev/null
}

# Canonicalize a working candidate to its real interpreter path, then exit. A single
# absolute path is quoting-safe (no multi-word `py -3` trap) and OS-agnostic.
_emit() {
    local p
    p="$("$@" -c 'import sys; print(sys.executable)' 2>/dev/null)"
    [ -n "$p" ] && { printf '%s\n' "$p"; exit 0; }
}

# Fail loud when a floor was requested but nothing met it — name the escape hatch.
_too_old=""   # version of the newest working-but-too-old interpreter seen (for the message)
_fail_floor() {
    {
        echo "ERROR: PCIS needs Python ${PCIS_MIN_PY}+, but the newest working interpreter found${_too_old:+ is $_too_old}."
        echo "       (macOS ships 3.9 as /usr/bin/python3 — the same trap as the Windows stub, one version older.)"
        echo "       Install 3.11+ — python.org or 'brew install python@3.11' — then name it explicitly:"
        echo "           PYTHON=python3.11 ./setup.sh"
    } >&2
    exit 3
}
_note_old() { _too_old="$("$@" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "$_too_old")"; }

# 1. Explicit override — authoritative. Honor it, but enforce the floor if one is set.
if [ -n "$PYTHON" ]; then
    if _meets_min $PYTHON; then printf '%s\n' "$PYTHON"; exit 0; fi
    _note_old $PYTHON; _fail_floor
fi

# 2. Project venv (Unix bin/ and Windows Scripts/ layouts), preferred when set up.
for VENV_PY in "$REPO/.venv/bin/python" "$REPO/.venv/Scripts/python.exe"; do
    if [ -x "$VENV_PY" ] && _works "$VENV_PY" && "$VENV_PY" -c 'import flask' >/dev/null 2>&1; then
        if _meets_min "$VENV_PY"; then _emit "$VENV_PY"; else _note_old "$VENV_PY"; fi
    fi
done

# 3. System interpreters — probed in order; the first that executes code (and meets the
#    floor, if any) wins.
for CAND in "py -3" python python3; do
    if _works $CAND; then
        if _meets_min $CAND; then _emit $CAND; else _note_old $CAND; fi
    fi
done

# 4. A venv that runs Python but lacks flask is still a valid interpreter (the replay
#    path needs no deps) — prefer it over failing.
for VENV_PY in "$REPO/.venv/bin/python" "$REPO/.venv/Scripts/python.exe"; do
    if [ -x "$VENV_PY" ] && _works "$VENV_PY"; then
        if _meets_min "$VENV_PY"; then _emit "$VENV_PY"; else _note_old "$VENV_PY"; fi
    fi
done

# 5a. A floor was requested but nothing met it — fail loud, don't hand back an
#     interpreter setup.sh can't finish with.
[ -n "${PCIS_MIN_PY:-}" ] && _fail_floor

# 5b. No floor, nothing resolved — emit a name so the caller fails loudly, not silently.
printf '%s\n' "python3"
