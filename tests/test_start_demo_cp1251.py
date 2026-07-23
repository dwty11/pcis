"""start_demo.sh's pre-flight [2/5] demo-tree integrity check must survive a Russian-locale
(cp1251) console. Regression guard for the demo_tree.json false-``integrity FAILED`` bug.

CRITICAL — this test drives ``start_demo.sh`` ITSELF, not its inline python block. The earlier
cp1251 test asserted the *function* (``verify_tree_integrity``) was safe while the real script
path stayed broken: the sweep that added ``encoding=`` to the ``.py`` files never reached inline
python embedded in a ``.sh`` entry point. Testing the function twice would miss it again — the
fix is exercising the entry point a first-time reader actually runs.

cp1251 is forced without editing the script: a ``sitecustomize.py`` dropped on ``PYTHONPATH``
makes bare ``open()`` default to cp1251 for every python the script spawns (including the
``$PYTHON -c`` at step 2), reproducing RU-Windows Git Bash.
"""
import os
import select
import shutil
import signal
import subprocess
import textwrap
import time

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
START_DEMO = os.path.join(REPO, "start_demo.sh")

pytestmark = pytest.mark.skipif(
    os.name != "posix" or shutil.which("bash") is None,
    reason="start_demo.sh is a bash entry point (POSIX shells only)",
)


def _run_start_demo_to_step2(env, timeout=90):
    """Launch start_demo.sh in its own process group; read stdout until the step-2 verdict
    line, then kill the whole group (before step 6 starts a server). Returns captured stdout."""
    proc = subprocess.Popen(
        ["bash", START_DEMO], cwd=REPO, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        start_new_session=True,
    )
    pgid = os.getpgid(proc.pid)
    lines = []
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            ready, _, _ = select.select([proc.stdout], [], [], remaining)
            if not ready:
                break
            line = proc.stdout.readline()
            if not line:  # EOF — the script exited
                break
            lines.append(line)
            if "demo_tree.json:" in line or "integrity FAILED" in line:
                break  # got the step-2 verdict; stop before the server step
    finally:
        try:
            os.killpg(pgid, signal.SIGKILL)  # reap the script + any backgrounded server
        except (ProcessLookupError, OSError):
            pass
        if proc.stdout:
            proc.stdout.close()
    return "".join(lines)


def test_start_demo_step2_reports_clean_under_cp1251(tmp_path):
    pytest.importorskip("flask", reason="start_demo.sh needs flask; skip to avoid a setup.sh bootstrap")

    (tmp_path / "sitecustomize.py").write_text(textwrap.dedent("""
        import builtins
        _open = builtins.open
        def _win_open(file, mode="r", buffering=-1, encoding=None, *a, **k):
            if "b" not in mode and encoding is None:
                encoding = "cp1251"            # Russian-locale Windows default
            return _open(file, mode, buffering, encoding, *a, **k)
        builtins.open = _win_open
    """), encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(tmp_path) + os.pathsep + env.get("PYTHONPATH", "")

    out = _run_start_demo_to_step2(env)

    assert "[2/5] Verifying demo tree integrity" in out, f"step 2 never ran:\n{out}"
    assert "integrity FAILED" not in out, (
        "start_demo.sh reported demo_tree.json integrity FAILED under a cp1251 console — the "
        f"demo tree is mis-decoded because step 2 reads it with a bare open():\n{out}"
    )
    assert "demo_tree.json: CLEAN" in out, f"step 2 did not report CLEAN:\n{out}"
