"""The Advocate replay demo must be READ-ONLY.

README's 60-second path (`./run_demo.sh`, default --replay) computes the counter against the
seeded tree and surfaces the move for display; it does NOT persist anything — a live `pcis
gardener` pass is what commits a counter permanently. The README states this plainly, so this
test guards it: if the replay demo ever starts writing to disk, the claim would silently drift
from true to false. This is the inverse of a normal "did it write?" test — it asserts it did NOT.
"""
import hashlib
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEMO = os.path.join(REPO, "demo", "advocate-demo")


def _snapshot(root):
    """SHA-256 of every file under `root`, keyed by relative path. Skips Python bytecode
    caches (`__pycache__`/`.pyc`) — importing modules writes those, and they are not the
    record the demo is claimed not to touch."""
    snap = {}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith(".pyc"):
                continue
            p = os.path.join(dirpath, f)
            with open(p, "rb") as fh:
                snap[os.path.relpath(p, root)] = hashlib.sha256(fh.read()).hexdigest()
    return snap


def test_replay_demo_writes_nothing_to_disk():
    before = _snapshot(DEMO)

    r = subprocess.run(
        ["bash", os.path.join(DEMO, "run_demo.sh")],
        capture_output=True, text=True, cwd=DEMO,
    )
    assert r.returncode == 0, f"run_demo.sh (replay) failed:\n{r.stdout}\n{r.stderr}"

    after = _snapshot(DEMO)

    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    assert not added and not removed, (
        "replay demo changed the set of files on disk (it must be read-only):\n"
        f"  added:   {added}\n  removed: {removed}"
    )
    changed = [p for p in before if before[p] != after.get(p)]
    assert not changed, (
        "replay demo modified file content on disk (it must be read-only; a live gardener "
        f"pass — not the demo — is what persists a counter): {changed}"
    )
