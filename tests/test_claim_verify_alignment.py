#!/usr/bin/env python3
"""Full-claim verify alignment (the format-drift fix).

The N2 gate's `pcis sign verify` must verify the SAME full-claim cert that the ceremony
signs (per SIGNING-CEREMONY-MANUAL), via the SAME algorithm as pcis_verify_claim.py — so
the two verify paths cannot disagree. Cert format: {claim, claim_hash, signature, public_key},
signature over canonical(claim); combined_root_hash lives INSIDE claim.

Whis's key guard = the agreement test: same cert+pin, `pcis sign verify` (snapshot=data/tree.json)
and pcis_verify_claim.py (snapshot=pulled) must return IDENTICAL verdicts, valid + each tamper.

Run: cd ~/openclaw-workspaces/pcis && python3 -m pytest tests/test_claim_verify_alignment.py -v
"""
import copy
import hashlib
import json
import os
import subprocess
import sys

import pytest

pytest.importorskip("nacl", reason="PyNaCl not installed")
import nacl.encoding  # noqa: E402
import nacl.signing  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, _ROOT)

# the off-machine verifier (workspace script) — the OTHER path in the agreement test
WS_VERIFY = "/Users/whis/.openclaw/workspace/pcis_verify_claim.py"


def _canonical(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha(b):
    return hashlib.sha256(b).hexdigest()


@pytest.fixture
def claim_setup(tmp_path):
    """A temp PCIS base with a VALID full-claim cert at data/approved_root_cert.json,
    signed by a key whose fingerprint == the on-disk pin. tree.json + a byte-identical
    pulled snapshot for the two-snapshot-source agreement check."""
    from knowledge_tree import (
        DEFAULT_BRANCHES,
        add_knowledge,
        compute_branch_hash,
        compute_root_hash,
        load_tree,
        now_utc,
    )

    base = tmp_path
    data = base / "data"
    data.mkdir()
    os.environ["PCIS_BASE_DIR"] = str(base)

    tree = {"version": 1, "created": now_utc(), "last_updated": now_utc(),
            "root_hash": "", "instance": "claim-test", "branches": {}}
    for b in DEFAULT_BRANCHES:
        tree["branches"][b] = {"hash": "", "leaves": []}
    add_knowledge(tree, "technical", "claim alignment test leaf", confidence=0.9)
    for bn in tree["branches"]:
        tree["branches"][bn]["hash"] = compute_branch_hash(tree["branches"][bn]["leaves"])
    tree["root_hash"] = compute_root_hash(tree)

    tree_bytes = json.dumps(tree, indent=2).encode()
    (data / "tree.json").write_bytes(tree_bytes)
    (base / "tree.snapshot.json").write_bytes(tree_bytes)  # off-machine pulled snapshot (same bytes)

    # the root_hash the gate will recompute from load_tree(data/tree.json)
    signed_root = compute_root_hash(load_tree(str(data / "tree.json")))

    sk = nacl.signing.SigningKey.generate()
    pub = sk.verify_key.encode(encoder=nacl.encoding.HexEncoder).decode()
    (data / "pcis_signing.pub").write_text(pub)
    pin = _sha(pub.encode())
    (data / "pcis_pin.fingerprint").write_text(pin)

    claim = {
        "schema": "pcis-approved-root/v1",
        "root_hash": signed_root,
        "combined_root_hash": _sha(b"combined-arbitrary"),  # verify_claim doesn't check this; leg (b) does
        "tree_snapshot_sha256": _sha(tree_bytes),
        "leaf_count": 1, "branch_count": len(DEFAULT_BRANCHES), "synapse_count": 0,
        "chain_index": 1, "prev_cert_sha256": None,
    }
    msg = _canonical(claim)
    cert = {"claim": claim, "claim_hash": _sha(msg),
            "signature": sk.sign(msg).signature.hex(), "public_key": pub}
    (data / "approved_root_cert.json").write_text(json.dumps(cert, indent=2))

    return {"base": str(base), "data": str(data),
            "cert_path": str(data / "approved_root_cert.json"),
            "snapshot": str(base / "tree.snapshot.json"),
            "tree": str(data / "tree.json"), "pin": pin, "cert": cert, "sk": sk, "pub": pub}


def _cli_sign_verify(setup):
    cli = os.path.join(_ROOT, "pcis", "cli.py")
    return subprocess.run(
        [sys.executable, cli, "--dir", setup["base"], "sign", "verify"],
        capture_output=True, text=True, env={**os.environ, "PCIS_BASE_DIR": setup["base"]},
    )


def _ws_claim_verify(setup):
    return subprocess.run(
        [sys.executable, WS_VERIFY, setup["cert_path"], setup["pin"], setup["snapshot"]],
        capture_output=True, text=True,
    )


# ── verify_claim (the canonical function) ──────────────────────────────────────

def test_verify_claim_valid_full_claim(claim_setup):
    from signing import verify_claim
    ok, detail = verify_claim(claim_setup["cert"], claim_setup["pin"], claim_setup["snapshot"])
    assert ok, detail
    assert "tree-consistent" in detail


@pytest.mark.parametrize("field", ["root_hash", "combined_root_hash", "tree_snapshot_sha256", "leaf_count"])
def test_verify_claim_rejects_any_tampered_field(claim_setup, field):
    from signing import verify_claim
    cert = copy.deepcopy(claim_setup["cert"])
    cur = cert["claim"][field]
    cert["claim"][field] = ("TAMPERED" if isinstance(cur, str) else 999999)
    ok, _ = verify_claim(cert, claim_setup["pin"], claim_setup["snapshot"])
    assert not ok  # signature covers canonical(claim) → ANY field change breaks it


def test_verify_claim_rejects_nonpinned_key(claim_setup):
    from signing import verify_claim
    sk2 = nacl.signing.SigningKey.generate()
    pub2 = sk2.verify_key.encode(encoder=nacl.encoding.HexEncoder).decode()
    claim = claim_setup["cert"]["claim"]
    msg = _canonical(claim)
    forged = {"claim": claim, "claim_hash": _sha(msg),
              "signature": sk2.sign(msg).signature.hex(), "public_key": pub2}
    ok, detail = verify_claim(forged, claim_setup["pin"], claim_setup["snapshot"])
    assert not ok and "fingerprint" in detail.lower()  # pubkey != pin, no embedded-key trust


# ── pcis sign verify (the gate's leg-a CLI) ────────────────────────────────────

def test_pcis_sign_verify_exit0_on_valid_claim(claim_setup):
    r = _cli_sign_verify(claim_setup)
    assert r.returncode == 0, f"stdout={r.stdout} stderr={r.stderr}"
    assert "VALID" in r.stdout


def test_pcis_sign_verify_nonzero_on_tampered_claim(claim_setup):
    cert = json.load(open(claim_setup["cert_path"]))
    cert["claim"]["root_hash"] = "TAMPERED"
    json.dump(cert, open(claim_setup["cert_path"], "w"))
    r = _cli_sign_verify(claim_setup)
    assert r.returncode != 0


# ── THE AGREEMENT TEST (Whis's key guard) ──────────────────────────────────────

def test_two_verify_paths_agree_valid_and_every_tamper(claim_setup):
    """`pcis sign verify` (snapshot=data/tree.json) and pcis_verify_claim.py (snapshot=pulled)
    must return IDENTICAL verdicts on the same cert+pin — valid AND each tampered field. This is
    the single test that would have caught the current drift."""
    # valid: both must PASS
    assert (_cli_sign_verify(claim_setup).returncode == 0) is True
    assert (_ws_claim_verify(claim_setup).returncode == 0) is True

    for field in ("root_hash", "combined_root_hash", "tree_snapshot_sha256"):
        cert = json.load(open(claim_setup["cert_path"]))
        orig = cert["claim"][field]
        cert["claim"][field] = "TAMPERED"
        json.dump(cert, open(claim_setup["cert_path"], "w"))
        gate_ok = _cli_sign_verify(claim_setup).returncode == 0
        off_ok = _ws_claim_verify(claim_setup).returncode == 0
        assert gate_ok == off_ok, f"paths DISAGREE on tampered {field}: gate={gate_ok} off={off_ok}"
        assert gate_ok is False, f"tampered {field} must be rejected by the gate"
        cert["claim"][field] = orig
        json.dump(cert, open(claim_setup["cert_path"], "w"))
