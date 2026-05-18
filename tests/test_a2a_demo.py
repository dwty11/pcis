#!/usr/bin/env python3
"""Tests for scripts/a2a_demo.py — A2A handoff smoke test.

The script is a runnable demonstration of the cryptographic handoff between
two agents. These tests verify the contract:
  - clean run signs and verifies end-to-end → exit 0 + "VERIFIED"
  - tampered run is detected by Agent B → exit 1 + "TAMPER DETECTED"
  - the handoff bundle file has the documented shape
"""

import json
import os
import subprocess
import sys

import pytest

pytest.importorskip("nacl", reason="PyNaCl not installed — skipping a2a_demo tests")

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
SCRIPT = os.path.join(_ROOT, "scripts", "a2a_demo.py")


# -----------------------------------------------------------------------
# Clean run — Agent A signs, Agent B verifies, exit 0
# -----------------------------------------------------------------------


def test_a2a_clean_run_verifies_end_to_end(tmp_path):
    bundle = tmp_path / "handoff.json"
    r = subprocess.run(
        [sys.executable, SCRIPT, "--bundle", str(bundle)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, (
        f"expected 0, got {r.returncode}\nstderr: {r.stderr}\nstdout: {r.stdout}"
    )
    out = r.stdout
    assert "AGENT A" in out
    assert "AGENT B" in out
    assert "VERIFIED END-TO-END" in out
    assert bundle.exists()


# -----------------------------------------------------------------------
# Tamper run — Agent B catches the modified bundle, exit 1
# -----------------------------------------------------------------------


def test_a2a_tamper_run_is_detected(tmp_path):
    bundle = tmp_path / "handoff.json"
    r = subprocess.run(
        [sys.executable, SCRIPT, "--bundle", str(bundle), "--tamper"],
        capture_output=True, text=True,
    )
    assert r.returncode == 1, (
        f"expected 1, got {r.returncode}\nstderr: {r.stderr}\nstdout: {r.stdout}"
    )
    out = r.stdout
    assert "TAMPER" in out
    # Detection must come from Agent B's verification side, not from a Python error
    assert "Traceback" not in r.stderr


# -----------------------------------------------------------------------
# Bundle shape — what Agent B receives must contain the four required parts
# -----------------------------------------------------------------------


def test_a2a_bundle_shape_is_correct(tmp_path):
    bundle = tmp_path / "handoff.json"
    r = subprocess.run(
        [sys.executable, SCRIPT, "--bundle", str(bundle)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr

    data = json.loads(bundle.read_text())
    assert data.get("agent_id") == "agent-a"
    assert "tree" in data
    assert "branches" in data["tree"]

    sig = data.get("signature", {})
    assert {"root_hash", "signature", "signed_at", "public_key"} <= set(sig)
    # Ed25519 sizes — fixed lengths
    assert len(sig["signature"]) == 128, "Ed25519 signature must be 128 hex chars"
    assert len(sig["public_key"]) == 64, "Ed25519 public key must be 64 hex chars"
    # The signed root must match the actual tree's stored root_hash
    assert sig["root_hash"] == data["tree"]["root_hash"]
