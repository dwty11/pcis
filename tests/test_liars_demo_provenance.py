#!/usr/bin/env python3
"""Provenance guard: `run_demo.sh --verify-self` must match CANONICAL_FINGERPRINT.txt.

Same failure class as the /hub 500 — a hygiene edit to a fingerprinted script
(stub_agent.py in 39df68e, after c49d1d0 had regenerated the fingerprint)
silently invalidated the provenance check while the rest of the suite stayed
green. The demo's own doctrine is that a skeptic runs --verify-self and compares
to the committed canonical file; if they diverge, the code reads as tampered.
This test asserts exactly that match, so a hygiene pass can never break
provenance silently again.
"""
import difflib
import subprocess
from pathlib import Path

LIARS = Path(__file__).resolve().parent.parent / "demo" / "liars-demo"


def test_verify_self_matches_canonical_fingerprint():
    live = subprocess.run(
        ["bash", "run_demo.sh", "--verify-self"],
        cwd=str(LIARS), capture_output=True, text=True, check=True,
    ).stdout.strip()
    canonical = (LIARS / "CANONICAL_FINGERPRINT.txt").read_text().strip()

    if live != canonical:
        diff = "\n".join(difflib.unified_diff(
            canonical.splitlines(), live.splitlines(),
            fromfile="CANONICAL_FINGERPRINT.txt", tofile="run_demo.sh --verify-self",
            lineterm="",
        ))
        raise AssertionError(
            "Provenance fingerprint diverged — a fingerprinted script changed "
            "without regenerating CANONICAL_FINGERPRINT.txt.\n"
            "Fix: cd demo/liars-demo && bash run_demo.sh --verify-self > CANONICAL_FINGERPRINT.txt\n"
            + diff
        )
