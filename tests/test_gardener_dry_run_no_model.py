"""`gardener --dry-run` must show the ATTACK without requiring a local model.

The quickstart's no-install moment is: add your own claim, run `pcis gardener
--dry-run`, and see that claim embedded in the adversarial prompt — the attack the
gardener will run on YOUR data. That must work with no Ollama and no pulled model.
And it must be explicit that this is the attack, not the result: a user who thinks
the gardener ran and found nothing is worse off than one who knows they need a model
for the real pass.
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cli(base, *args, model="no-such-model-zzz9"):
    return subprocess.run(
        [sys.executable, "-m", "pcis.cli", "--dir", base, *args],
        capture_output=True, text=True, cwd=REPO, timeout=90,
        env={**os.environ, "PCIS_GARDENER_MODEL": model},
    )


def test_dry_run_shows_attack_and_exits_clean_without_a_usable_model(tmp_path):
    base = str(tmp_path)
    _cli(base, "init")
    _cli(base, "add", "technical",
         "Postgres beats MySQL for every workload we run", "--confidence", "0.9")
    r = _cli(base, "gardener", "--dry-run")
    out = r.stdout + r.stderr
    # 1. The no-install path must not hard-fail on a missing/unreachable model.
    assert r.returncode == 0, f"--dry-run must exit clean with no usable model:\n{out}"
    # 2. The user's OWN claim appears in the shown attack (the prompt).
    assert "Postgres beats MySQL" in out, "the user's claim must appear in the attack"
    # 3. Explicit that this is the attack, not the result, and points at a real model.
    assert "ollama" in out.lower(), "must guide the user toward a local model"
    assert "not the result" in out.lower() or "attack" in out.lower(), \
        "must distinguish the attack shown from the (ungenerated) result"
