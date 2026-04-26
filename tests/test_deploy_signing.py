#!/usr/bin/env python3
"""Tests for scripts/deploy_signing.py and scripts/back_sign_leaves.py."""

import json
import os
import sys

import pytest

pytest.importorskip("nacl", reason="PyNaCl not installed — skipping deploy_signing tests")

# Make core/ and scripts/ importable
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
sys.path.insert(0, _ROOT)

from knowledge_tree import (
    DEFAULT_BRANCHES,
    add_knowledge,
    compute_branch_hash,
    compute_root_hash,
    load_tree,
    now_utc,
)


# -----------------------------------------------------------------------
# Fixture — arbitrary tree location (NOT under data/) to exercise the
# "next-to-tree" signature placement that distinguishes deploy_signing
# from signing.sign_root.
# -----------------------------------------------------------------------


@pytest.fixture
def tmp_tree(tmp_path, monkeypatch):
    """Set up a tree at <tmp>/custom_dir/my_tree.json (deliberately NOT data/)."""
    monkeypatch.setenv("PCIS_BASE_DIR", str(tmp_path))

    custom_dir = tmp_path / "custom_dir"
    custom_dir.mkdir()
    tree_path = custom_dir / "my_tree.json"

    tree = {
        "version": 1,
        "created": now_utc(),
        "last_updated": now_utc(),
        "root_hash": "",
        "instance": "test",
        "branches": {},
    }
    for branch in DEFAULT_BRANCHES:
        tree["branches"][branch] = {"hash": "", "leaves": []}

    add_knowledge(tree, "technical", "Use proper SHA-256 hashing", confidence=0.85)
    add_knowledge(tree, "lessons", "Verify before trusting", confidence=0.90)

    for bname in tree["branches"]:
        tree["branches"][bname]["hash"] = compute_branch_hash(
            tree["branches"][bname]["leaves"]
        )
    tree["root_hash"] = compute_root_hash(tree)

    with open(tree_path, "w") as f:
        json.dump(tree, f, indent=2)

    key_dir = tmp_path / "keys"

    return {
        "base": str(tmp_path),
        "tree_path": str(tree_path),
        "tree_dir": str(custom_dir),
        "key_dir": str(key_dir),
    }


# -----------------------------------------------------------------------
# deploy_signing tests
# -----------------------------------------------------------------------


def test_deploy_creates_keypair_signature_and_verifies(tmp_tree):
    from deploy_signing import deploy_signing

    result = deploy_signing(tmp_tree["tree_path"], tmp_tree["key_dir"])

    assert result["valid"] is True
    assert "root_hash" in result
    assert len(result["signature"]) == 128  # 64 bytes hex
    assert "signed_at" in result
    assert "public_key" in result

    # Keypair exists
    assert os.path.exists(os.path.join(tmp_tree["key_dir"], "pcis_signing.key"))
    assert os.path.exists(os.path.join(tmp_tree["key_dir"], "pcis_signing.pub"))


def test_deploy_signature_path_is_next_to_tree(tmp_tree):
    """Signature must land in the tree's directory, NOT in <base>/data/."""
    from deploy_signing import deploy_signing

    deploy_signing(tmp_tree["tree_path"], tmp_tree["key_dir"])

    expected_sig = os.path.join(tmp_tree["tree_dir"], "root_signature.json")
    not_expected = os.path.join(tmp_tree["base"], "data", "root_signature.json")

    assert os.path.exists(expected_sig), (
        f"Signature should land at {expected_sig}"
    )
    assert not os.path.exists(not_expected), (
        f"Signature should NOT land at default data/ path {not_expected}"
    )


def test_deploy_dry_run_writes_nothing(tmp_tree):
    from deploy_signing import deploy_signing

    result = deploy_signing(
        tmp_tree["tree_path"], tmp_tree["key_dir"], dry_run=True
    )

    assert result.get("dry_run") is True

    # No signature file
    sig_path = os.path.join(tmp_tree["tree_dir"], "root_signature.json")
    assert not os.path.exists(sig_path)

    # No key files
    assert not os.path.exists(
        os.path.join(tmp_tree["key_dir"], "pcis_signing.key")
    )
    assert not os.path.exists(
        os.path.join(tmp_tree["key_dir"], "pcis_signing.pub")
    )


def test_deploy_reuses_existing_keypair(tmp_tree):
    """Second deploy reuses keys, doesn't fail with FileExistsError."""
    from deploy_signing import deploy_signing

    first = deploy_signing(tmp_tree["tree_path"], tmp_tree["key_dir"])
    assert first["valid"] is True

    # Capture key bytes to confirm they are not regenerated
    priv_path = os.path.join(tmp_tree["key_dir"], "pcis_signing.key")
    with open(priv_path, "r") as f:
        original_key = f.read()

    second = deploy_signing(tmp_tree["tree_path"], tmp_tree["key_dir"])
    assert second["valid"] is True

    with open(priv_path, "r") as f:
        new_key = f.read()
    assert original_key == new_key, "Existing keypair must not be regenerated"


def test_deploy_signature_round_trip_with_signing_module(tmp_tree):
    """Signature produced by deploy_signing.py must verify via signing.verify_root_standalone."""
    from deploy_signing import deploy_signing
    from signing import verify_root_standalone

    result = deploy_signing(tmp_tree["tree_path"], tmp_tree["key_dir"])

    verify = verify_root_standalone(
        result["root_hash"], result["signature"], result["public_key"]
    )
    assert verify["valid"] is True


# -----------------------------------------------------------------------
# back_sign_leaves tests
# -----------------------------------------------------------------------


def test_back_sign_marks_all_leaves(tmp_tree):
    from back_sign_leaves import back_sign_tree

    count = back_sign_tree(tmp_tree["tree_path"])
    assert count == 2  # fixture adds two leaves

    tree = load_tree(tmp_tree["tree_path"])
    leaves_marked = 0
    for branch in tree["branches"].values():
        for leaf in branch.get("leaves", []):
            assert leaf.get("signed") is True, f"Leaf {leaf['id']} not marked signed"
            assert "root_at_signing" in leaf, "Leaf missing root_at_signing"
            leaves_marked += 1
    assert leaves_marked == 2


def test_back_sign_root_at_signing_matches_root(tmp_tree):
    """Every leaf's root_at_signing must equal the tree's actual root hash."""
    from back_sign_leaves import back_sign_tree

    back_sign_tree(tmp_tree["tree_path"])

    tree = load_tree(tmp_tree["tree_path"])
    actual_root = compute_root_hash(tree)

    for branch in tree["branches"].values():
        for leaf in branch.get("leaves", []):
            assert leaf["root_at_signing"] == actual_root, (
                f"Leaf {leaf['id']} root_at_signing {leaf['root_at_signing'][:12]} "
                f"!= actual root {actual_root[:12]}"
            )


def test_back_sign_does_not_change_root(tmp_tree):
    """Adding signed/root_at_signing to leaves must not change leaf hashes
    (which are computed from content+branch+timestamp only) and therefore
    must not change the tree's root hash."""
    from back_sign_leaves import back_sign_tree

    tree_before = load_tree(tmp_tree["tree_path"])
    root_before = compute_root_hash(tree_before)

    back_sign_tree(tmp_tree["tree_path"])

    tree_after = load_tree(tmp_tree["tree_path"])
    root_after = compute_root_hash(tree_after)

    assert root_before == root_after, (
        "Root hash must not change after back-signing"
    )


def test_back_sign_idempotent(tmp_tree):
    """Running twice in a row leaves the tree consistent (same root, signed=True)."""
    from back_sign_leaves import back_sign_tree

    count1 = back_sign_tree(tmp_tree["tree_path"])
    count2 = back_sign_tree(tmp_tree["tree_path"])
    assert count1 == count2 == 2

    tree = load_tree(tmp_tree["tree_path"])
    for branch in tree["branches"].values():
        for leaf in branch.get("leaves", []):
            assert leaf["signed"] is True
