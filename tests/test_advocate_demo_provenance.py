"""Provenance guard: the Advocate Demo's --verify-self must match CANONICAL_FINGERPRINT.txt.

Same failure class as the liars-demo `39df68e` regression — a hygiene edit to a
fingerprinted script or fixture that diverges from the committed fingerprint reads as
tampered to a skeptic running `--verify-self`. This test fails the build the moment they
diverge, so the divergence can never ship silently.
"""
import subprocess
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parent.parent / "demo" / "advocate-demo"


def test_verify_self_matches_canonical_fingerprint():
    result = subprocess.run(
        [sys.executable, str(DEMO / "verify_self.py")],
        capture_output=True, text=True, cwd=str(DEMO),
    )
    assert result.returncode == 0, (
        "Advocate Demo verify-self does not match CANONICAL_FINGERPRINT.txt — a "
        "fingerprinted script or fixture changed without the fingerprint being "
        "regenerated:\n" + result.stdout + "\n" + result.stderr
    )
    assert "matches" in result.stdout
