#!/usr/bin/env python3
"""Unit tests for scripts/resolve_python.sh.

The resolver must return an interpreter that ACTUALLY EXECUTES PYTHON — tested as a
property, not by name. The Windows Store `python3` is a stub that exists on PATH but
prints "Python" and runs nothing; a name/existence check picks it and the demo dies.
The resolver probes every candidate (`-c "print(1)"` must print `1`) and returns the
real interpreter's absolute path, so any broken candidate — Windows stub or otherwise —
fails the same way. It still prefers the project venv setup.sh populated.
"""
import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESOLVER = REPO_ROOT / "scripts" / "resolve_python.sh"
_BASE_PATH = "/usr/bin:/bin"  # for bash/coreutils; test dir is prepended so it shadows


def _script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _real_python(path: Path, flask: bool = True) -> Path:
    """A stand-in interpreter that answers the resolver's probes like real Python:
    `-c print(1)` -> 1, `-c import flask` -> 0/1, `-c sys.executable` -> its own path."""
    return _script(path, (
        'if [ "$1" = "-c" ]; then case "$2" in\n'
        '  *"print(1)"*) echo 1;;\n'
        f'  *"import flask"*) exit {0 if flask else 1};;\n'
        '  *"sys.executable"*) echo "$0";;\n'
        'esac; fi\n'
    ))


def _stub(path: Path) -> Path:
    """The Windows Store python3 stub: exists, prints 'Python', runs no code."""
    return _script(path, 'echo "Python"\nexit 0\n')


def _resolve(repo: Path, path=None, env_extra=None) -> str:
    env = dict(os.environ, REPO=str(repo))
    env.pop("PYTHON", None)
    if path:
        env["PATH"] = path
    if env_extra:
        env.update(env_extra)
    out = subprocess.run(["bash", str(RESOLVER)], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def _executes(interpreter: str, path=None) -> bool:
    env = dict(os.environ)
    if path:
        env["PATH"] = path
    r = subprocess.run([interpreter, "-c", "print(1)"], capture_output=True, text=True, env=env)
    return r.stdout.strip() == "1"


def test_returned_interpreter_actually_executes_python(tmp_path):
    d = tmp_path / "bin"; d.mkdir()
    _stub(d / "python3")               # the stub is first-in-line
    _real_python(d / "python", flask=False)
    path = f"{d}:{_BASE_PATH}"
    out = _resolve(tmp_path, path=path)
    assert _executes(out, path=path), f"resolver returned a non-working interpreter: {out!r}"


def test_rejects_the_stub_and_picks_a_real_interpreter(tmp_path):
    d = tmp_path / "bin"; d.mkdir()
    _stub(d / "python3")               # `python3` is the stub
    _real_python(d / "python", flask=False)
    out = _resolve(tmp_path, path=f"{d}:{_BASE_PATH}")
    assert out == str(d / "python"), f"expected the real python, got {out!r}"


def test_prefers_venv_python_when_it_has_flask(tmp_path):
    venv = tmp_path / ".venv" / "bin"; venv.mkdir(parents=True)
    py = _real_python(venv / "python", flask=True)
    assert _resolve(tmp_path) == str(py)


def test_venv_without_flask_falls_through_to_a_working_system_python(tmp_path):
    venv = tmp_path / ".venv" / "bin"; venv.mkdir(parents=True)
    _real_python(venv / "python", flask=False)   # venv runs, but no flask
    d = tmp_path / "bin"; d.mkdir()
    _real_python(d / "python", flask=False)       # a working system python
    out = _resolve(tmp_path, path=f"{d}:{_BASE_PATH}")
    assert out == str(d / "python")


def test_honors_explicit_python_override(tmp_path):
    assert _resolve(tmp_path, env_extra={"PYTHON": "/custom/python"}) == "/custom/python"


# ── Version floor (PCIS_MIN_PY) ──────────────────────────────────────────────
# setup.sh needs 3.10+ (the editable install requires a modern pip; macOS ships 3.9
# as /usr/bin/python3 — the same class of trap as the Windows stub, one version older).
# When PCIS_MIN_PY is set the resolver must fail LOUD instead of returning an interpreter
# the caller can't finish with. run_demo.sh's zero-dep replay leaves it unset.

def _versioned(path, meets_min=True, flask=False):
    """A stand-in interpreter that reports whether it meets the floor: the resolver's
    _meets_min probe (its code contains 'version_info') exits 0 (meets) or 1 (too old)."""
    return _script(path, (
        'if [ "$1" = "-c" ]; then case "$2" in\n'
        '  *"print(1)"*) echo 1;;\n'
        f'  *"version_info"*) exit {0 if meets_min else 1};;\n'
        f'  *"import flask"*) exit {0 if flask else 1};;\n'
        '  *"sys.executable"*) echo "$0";;\n'
        'esac; fi\n'
    ))


def _resolve_raw(repo, path=None, env_extra=None):
    """Like _resolve, but returns the CompletedProcess (may be a non-zero failure)."""
    env = dict(os.environ, REPO=str(repo)); env.pop("PYTHON", None)
    if path:
        env["PATH"] = path
    if env_extra:
        env.update(env_extra)
    return subprocess.run(["bash", str(RESOLVER)], capture_output=True, text=True, env=env)


def test_min_version_gate_fails_loud_and_names_the_override(tmp_path):
    # Nothing can meet an impossible floor -> fail (non-zero) and name the PYTHON= escape
    # hatch; never silently hand back an interpreter setup.sh can't finish with.
    r = _resolve_raw(tmp_path, env_extra={"PCIS_MIN_PY": "3.99"})
    assert r.returncode != 0, f"expected a loud failure, got stdout={r.stdout!r}"
    assert "PYTHON=" in r.stderr, f"error must name the PYTHON= override: {r.stderr!r}"


def test_min_version_gate_picks_a_new_enough_interpreter(tmp_path):
    d = tmp_path / "bin"; d.mkdir()
    _versioned(d / "python", meets_min=False)          # too old, tried first
    new = _versioned(d / "python3", meets_min=True)     # meets the floor
    r = _resolve_raw(tmp_path, path=f"{d}:{_BASE_PATH}", env_extra={"PCIS_MIN_PY": "3.10"})
    assert r.returncode == 0 and r.stdout.strip() == str(new), (r.returncode, r.stdout, r.stderr)


def test_no_floor_still_resolves_an_older_interpreter(tmp_path):
    # The zero-dep replay path (run_demo.sh, no PCIS_MIN_PY) must keep working on 3.9.
    d = tmp_path / "bin"; d.mkdir()
    old = _versioned(d / "python", meets_min=False)
    r = _resolve_raw(tmp_path, path=f"{d}:{_BASE_PATH}")   # no PCIS_MIN_PY set
    assert r.returncode == 0 and r.stdout.strip() == str(old), (r.returncode, r.stdout, r.stderr)


def test_too_old_explicit_override_is_rejected(tmp_path):
    old = _versioned(tmp_path / "oldpy", meets_min=False)
    r = _resolve_raw(tmp_path, env_extra={"PYTHON": str(old), "PCIS_MIN_PY": "3.10"})
    assert r.returncode != 0, f"a too-old PYTHON= override must be rejected: {r.stdout!r}"
