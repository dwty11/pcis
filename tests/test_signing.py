#!/usr/bin/env python3
"""Tests for core/signing.py — ed25519 root signing."""

import json
import os
import stat
import sys
import tempfile

import pytest

nacl = pytest.importorskip("nacl", reason="PyNaCl not installed — skipping signing tests")

# Ensure core/ is importable
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, _ROOT)

from signing import (
    generate_keypair,
    sign_root,
    verify_root,
    verify_root_standalone,
    export_public_key,
    PRIVATE_KEY_FILE,
    PUBLIC_KEY_FILE,
    SIGNATURE_FILE,
)
from knowledge_tree import (
    load_tree,
    add_knowledge,
    compute_root_hash,
    DEFAULT_BRANCHES,
    now_utc,
)


@pytest.fixture
def tmp_pcis(tmp_path, monkeypatch):
    """Set up a temporary PCIS directory with an initialized tree."""
    monkeypatch.setenv("PCIS_BASE_DIR", str(tmp_path))
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    tree = {
        "meta": {"created": now_utc(), "version": "1.4.0"},
        "branches": {},
    }
    for branch in DEFAULT_BRANCHES:
        tree["branches"][branch] = {"hash": "", "leaves": []}

    add_knowledge(tree, "technical", "REST APIs should use plural nouns", confidence=0.85)
    add_knowledge(tree, "lessons", "Always verify before trusting", confidence=0.90)

    for bname in tree["branches"]:
        from knowledge_tree import compute_branch_hash
        tree["branches"][bname]["hash"] = compute_branch_hash(
            tree["branches"][bname]["leaves"]
        )
    tree["root_hash"] = compute_root_hash(tree)

    tree_path = data_dir / "tree.json"
    with open(tree_path, "w") as f:
        json.dump(tree, f, indent=2)

    return tmp_path


# -----------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------


def test_generate_keypair_creates_files(tmp_pcis):
    priv_path, pub_path = generate_keypair()
    assert os.path.exists(priv_path)
    assert os.path.exists(pub_path)
    assert priv_path.endswith(PRIVATE_KEY_FILE)
    assert pub_path.endswith(PUBLIC_KEY_FILE)


def test_generate_keypair_refuses_overwrite(tmp_pcis):
    generate_keypair()
    with pytest.raises(FileExistsError):
        generate_keypair()


def test_sign_root_produces_valid_signature(tmp_pcis):
    generate_keypair()
    result = sign_root()
    assert "root_hash" in result
    assert "signature" in result
    assert "signed_at" in result
    assert "public_key" in result
    # Signature should be 128 hex chars (64 bytes)
    assert len(result["signature"]) == 128
    # Verify the signature file was written
    sig_path = os.path.join(str(tmp_pcis), "data", SIGNATURE_FILE)
    assert os.path.exists(sig_path)


def test_verify_root_valid(tmp_pcis):
    generate_keypair()
    sign_root()
    result = verify_root()
    assert result["valid"] is True
    assert "Signature is valid" in result["detail"]


def test_verify_root_tampered(tmp_pcis):
    """Modify tree after signing — verification should fail."""
    generate_keypair()
    sign_root()

    # Tamper with the tree
    tree_path = os.path.join(str(tmp_pcis), "data", "tree.json")
    with open(tree_path, "r") as f:
        tree = json.load(f)
    add_knowledge(tree, "technical", "This is new tampered knowledge", confidence=0.5)
    from knowledge_tree import compute_branch_hash
    for bname in tree["branches"]:
        tree["branches"][bname]["hash"] = compute_branch_hash(
            tree["branches"][bname]["leaves"]
        )
    tree["root_hash"] = compute_root_hash(tree)
    with open(tree_path, "w") as f:
        json.dump(tree, f, indent=2)

    result = verify_root()
    assert result["valid"] is False


def test_verify_root_wrong_key(tmp_pcis):
    """Sign with one key, verify with another — should fail."""
    generate_keypair()
    sign_root()

    # Generate a different keypair in a separate directory
    other_dir = os.path.join(str(tmp_pcis), "other_keys")
    os.makedirs(other_dir)
    other_priv, other_pub = generate_keypair(key_dir=other_dir)

    result = verify_root(public_key_path=other_pub)
    assert result["valid"] is False
    assert "FAILED" in result["detail"]


def test_verify_standalone(tmp_pcis):
    generate_keypair()
    sig = sign_root()
    result = verify_root_standalone(
        sig["root_hash"], sig["signature"], sig["public_key"]
    )
    assert result["valid"] is True


def test_export_public_key_format(tmp_pcis):
    generate_keypair()
    pub_hex = export_public_key()
    # ed25519 public key is 32 bytes = 64 hex chars
    assert len(pub_hex) == 64
    # Should be valid hex
    int(pub_hex, 16)


def test_sign_requires_keypair(tmp_pcis):
    """Signing without a keypair should raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        sign_root()


def test_private_key_permissions(tmp_pcis):
    priv_path, _ = generate_keypair()
    mode = os.stat(priv_path).st_mode
    # Check that only owner has read/write (0600)
    assert mode & stat.S_IRUSR  # owner can read
    assert mode & stat.S_IWUSR  # owner can write
    assert not (mode & stat.S_IRGRP)  # group cannot read
    assert not (mode & stat.S_IWGRP)  # group cannot write
    assert not (mode & stat.S_IROTH)  # others cannot read
    assert not (mode & stat.S_IWOTH)  # others cannot write


def test_verify_standalone_bad_signature(tmp_pcis):
    """Standalone verification with a garbage signature should fail."""
    generate_keypair()
    sig = sign_root()
    bad_sig = "00" * 64  # 64 bytes of zeros
    result = verify_root_standalone(sig["root_hash"], bad_sig, sig["public_key"])
    assert result["valid"] is False


def test_export_public_key_missing(tmp_pcis):
    """export_public_key should raise if no key exists."""
    with pytest.raises(FileNotFoundError):
        export_public_key()
