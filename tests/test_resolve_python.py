#!/usr/bin/env python3
"""Unit tests for scripts/resolve_python.sh.

The resolver makes `bash setup.sh && bash start_demo.sh` work with no manual
`source .venv/bin/activate`: start_demo.sh asks the resolver which interpreter
to use, and the resolver prefers the project virtualenv setup.sh populated —
but only if that venv can actually import flask, so a stale/empty venv falls
back to system python3 instead of hard-failing the demo.
"""

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESOLVER = REPO_ROOT / "scripts" / "resolve_python.sh"


def _make_fake_venv_python(repo: Path, flask_ok: bool) -> Path:
    """Create repo/.venv/bin/python as a stub whose `-c "import flask"` probe
    exits 0 (flask present) or 1 (flask absent)."""
    py = repo / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("#!/bin/bash\nexit %d\n" % (0 if flask_ok else 1))
    py.chmod(py.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return py


def _resolve(repo: Path, env_extra=None) -> str:
    env = dict(os.environ, REPO=str(repo))
    env.pop("PYTHON", None)
    if env_extra:
        env.update(env_extra)
    out = subprocess.run(
        ["bash", str(RESOLVER)], capture_output=True, text=True, env=env
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_prefers_venv_python_when_it_has_flask(tmp_path):
    py = _make_fake_venv_python(tmp_path, flask_ok=True)
    assert _resolve(tmp_path) == str(py)


def test_falls_back_to_python3_when_venv_lacks_flask(tmp_path):
    _make_fake_venv_python(tmp_path, flask_ok=False)
    assert _resolve(tmp_path) == "python3"


def test_falls_back_to_python3_when_no_venv(tmp_path):
    assert _resolve(tmp_path) == "python3"


def test_honors_explicit_python_override(tmp_path):
    _make_fake_venv_python(tmp_path, flask_ok=True)
    assert _resolve(tmp_path, {"PYTHON": "/custom/python"}) == "/custom/python"
