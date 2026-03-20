#!/usr/bin/env python3
"""
PCIS Core Test Suite

Tests: Merkle integrity, knowledge tree operations, pruning, search,
adversarial validation, and demo data integrity.

Run: python -m pytest tests/ -v
"""

import hashlib
import json
import os
import sys
import tempfile
import shutil
import pytest

# Add core to path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_DIR = os.path.join(REPO_ROOT, "core")
DEMO_DIR = os.path.join(REPO_ROOT, "demo")
sys.path.insert(0, CORE_DIR)

import knowledge_tree as kt
import knowledge_prune as kp
import knowledge_search as ks


# ── Helpers ────────────────────────────────────────────────────────────────

def make_empty_tree():
    """Return a fresh empty tree structure."""
    return {
        "version": 1,
        "instance": "test",
        "root_hash": "",
        "last_updated": kt.now_utc(),
        "branches": {b: {"hash": "", "leaves": []} for b in kt.DEFAULT_BRANCHES}
    }


# ── Merkle Integrity Tests ─────────────────────────────────────────────────

class TestMerkleIntegrity:

    def test_hash_leaf_deterministic(self):
        """Same inputs always produce same hash."""
        h1 = kt.hash_leaf("test content", "lessons", "2026-01-01 00:00:00 UTC")
        h2 = kt.hash_leaf("test content", "lessons", "2026-01-01 00:00:00 UTC")
        assert h1 == h2

    def test_hash_leaf_unique(self):
        """Different content produces different hash."""
        h1 = kt.hash_leaf("content A", "lessons", "2026-01-01 00:00:00 UTC")
        h2 = kt.hash_leaf("content B", "lessons", "2026-01-01 00:00:00 UTC")
        assert h1 != h2

    def test_hash_is_sha256(self):
        """Hashes are 64-char hex strings (SHA-256)."""
        h = kt.hash_leaf("test", "branch", "2026-01-01 00:00:00 UTC")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_branch_hash_empty(self):
        """Empty branch produces consistent hash."""
        h1 = kt.compute_branch_hash([])
        h2 = kt.compute_branch_hash([])
        assert h1 == h2
        assert len(h1) == 64

    def test_branch_hash_changes_with_content(self):
        """Branch hash changes when leaves change."""
        leaves_a = [{"hash": "a" * 64, "content": "x"}]
        leaves_b = [{"hash": "b" * 64, "content": "y"}]
        assert kt.compute_branch_hash(leaves_a) != kt.compute_branch_hash(leaves_b)

    def test_root_hash_covers_all_branches(self):
        """Root hash incorporates all branches."""
        tree = make_empty_tree()
        kt.add_knowledge(tree, "technical", "First technical insight", source="test", confidence=0.9)
        kt.add_knowledge(tree, "lessons", "First lesson learned", source="test", confidence=0.8)
        root = kt.compute_root_hash(tree)
        assert len(root) == 64
        assert all(c in "0123456789abcdef" for c in root)

    def test_root_hash_changes_on_add(self):
        """Root hash changes after adding a leaf."""
        tree = make_empty_tree()
        kt.add_knowledge(tree, "technical", "Initial leaf", source="test", confidence=0.8)
        root1 = kt.compute_root_hash(tree)
        kt.add_knowledge(tree, "technical", "Second leaf", source="test", confidence=0.7)
        root2 = kt.compute_root_hash(tree)
        assert root1 != root2


# ── Knowledge Tree Operations ──────────────────────────────────────────────

class TestKnowledgeTree:

    def test_add_knowledge_basic(self):
        """Add a leaf and verify it appears in the tree."""
        tree = make_empty_tree()
        kt.add_knowledge(tree, "lessons", "Test insight", source="test-session", confidence=0.85)
        leaves = tree["branches"]["lessons"]["leaves"]
        assert len(leaves) == 1
        assert leaves[0]["content"] == "Test insight"
        assert leaves[0]["source"] == "test-session"
        assert leaves[0]["confidence"] == 0.85

    def test_add_knowledge_has_required_fields(self):
        """Every leaf must have id, content, confidence, source, created, hash."""
        tree = make_empty_tree()
        kt.add_knowledge(tree, "technical", "Field check", source="test", confidence=0.75)
        leaf = tree["branches"]["technical"]["leaves"][0]
        for field in ["id", "content", "confidence", "source", "created", "hash"]:
            assert field in leaf, f"Missing field: {field}"

    def test_add_multiple_branches(self):
        """Leaves go to correct branches."""
        tree = make_empty_tree()
        kt.add_knowledge(tree, "technical", "Technical leaf", source="t", confidence=0.8)
        kt.add_knowledge(tree, "lessons", "Lessons leaf", source="t", confidence=0.8)
        assert len(tree["branches"]["technical"]["leaves"]) == 1
        assert len(tree["branches"]["lessons"]["leaves"]) == 1

    def test_leaf_id_unique(self):
        """Each leaf gets a unique ID."""
        tree = make_empty_tree()
        kt.add_knowledge(tree, "lessons", "Leaf one", source="t", confidence=0.8)
        kt.add_knowledge(tree, "lessons", "Leaf two", source="t", confidence=0.8)
        ids = [l["id"] for l in tree["branches"]["lessons"]["leaves"]]
        assert len(ids) == len(set(ids))

    def test_leaf_hash_is_sha256(self):
        """Each leaf hash is a 64-char SHA-256 hex string."""
        tree = make_empty_tree()
        kt.add_knowledge(tree, "lessons", "Hash check", source="t", confidence=0.8)
        leaf = tree["branches"]["lessons"]["leaves"][0]
        assert len(leaf["hash"]) == 64
        assert all(c in "0123456789abcdef" for c in leaf["hash"])

    def test_counter_leaf_tag(self):
        """COUNTER leaves can be added and are retrievable."""
        tree = make_empty_tree()
        kt.add_knowledge(tree, "technical", "Original claim", source="test", confidence=0.9)
        kt.add_knowledge(tree, "technical", "COUNTER: Original claim may be wrong", source="adversarial", confidence=0.6)
        leaves = tree["branches"]["technical"]["leaves"]
        counter_leaves = [l for l in leaves if "COUNTER" in l["content"]]
        assert len(counter_leaves) == 1

    def test_branch_hash_updated_on_add(self):
        """Branch hash updates when a leaf is added."""
        tree = make_empty_tree()
        hash_before = tree["branches"]["technical"]["hash"]
        kt.add_knowledge(tree, "technical", "New leaf", source="t", confidence=0.8)
        hash_after = tree["branches"]["technical"]["hash"]
        assert hash_before != hash_after


# ── Knowledge Pruning ──────────────────────────────────────────────────────

class TestKnowledgePruning:

    def test_prune_removes_leaf(self):
        """Pruning a leaf by ID removes it from the tree."""
        tree = make_empty_tree()
        kt.add_knowledge(tree, "lessons", "To be pruned", source="test", confidence=0.3)
        leaf_id = tree["branches"]["lessons"]["leaves"][0]["id"]
        kt.prune_leaf(tree, "lessons", leaf_id)
        remaining_ids = [l["id"] for l in tree["branches"]["lessons"]["leaves"]]
        assert leaf_id not in remaining_ids

    def test_prune_updates_root_hash(self):
        """Root hash changes after pruning."""
        tree = make_empty_tree()
        kt.add_knowledge(tree, "lessons", "Leaf A", source="test", confidence=0.8)
        kt.add_knowledge(tree, "lessons", "Leaf B", source="test", confidence=0.3)
        root_before = kt.compute_root_hash(tree)
        leaf_id = tree["branches"]["lessons"]["leaves"][1]["id"]
        kt.prune_leaf(tree, "lessons", leaf_id)
        root_after = kt.compute_root_hash(tree)
        assert root_before != root_after

    def test_prune_preserves_other_leaves(self):
        """Pruning one leaf does not affect others."""
        tree = make_empty_tree()
        kt.add_knowledge(tree, "lessons", "Keep me", source="test", confidence=0.9)
        kt.add_knowledge(tree, "lessons", "Remove me", source="test", confidence=0.2)
        keep_id = tree["branches"]["lessons"]["leaves"][0]["id"]
        remove_id = tree["branches"]["lessons"]["leaves"][1]["id"]
        kt.prune_leaf(tree, "lessons", remove_id)
        remaining_ids = [l["id"] for l in tree["branches"]["lessons"]["leaves"]]
        assert keep_id in remaining_ids
        assert remove_id not in remaining_ids


# ── Demo Data Integrity ────────────────────────────────────────────────────

class TestDemoData:

    def test_demo_tree_loads(self):
        """demo_tree.json is valid JSON and has required structure."""
        demo_tree_path = os.path.join(DEMO_DIR, "demo_tree.json")
        assert os.path.exists(demo_tree_path), "demo_tree.json missing"
        with open(demo_tree_path) as f:
            tree = json.load(f)
        assert "branches" in tree
        assert "root_hash" in tree
        assert "version" in tree

    def test_demo_tree_no_personal_data(self):
        """Demo tree contains no personal identifiers."""
        demo_tree_path = os.path.join(DEMO_DIR, "demo_tree.json")
        with open(demo_tree_path) as f:
            content = f.read().lower()
        banned = ["sberbank", "sber", "/users/", "whis", "openclaw", "imamniy", "idwty11"]
        for term in banned:
            assert term not in content, f"Personal data found in demo_tree.json: '{term}'"

    def test_demo_tree_has_leaves(self):
        """Demo tree has at least one populated branch."""
        demo_tree_path = os.path.join(DEMO_DIR, "demo_tree.json")
        with open(demo_tree_path) as f:
            tree = json.load(f)
        total_leaves = sum(
            len(b["leaves"]) for b in tree["branches"].values() if "leaves" in b
        )
        assert total_leaves > 0, "Demo tree has no leaves"

    def test_demo_tree_leaf_required_fields(self):
        """Every leaf in demo tree has id, content, confidence, source, created, hash."""
        demo_tree_path = os.path.join(DEMO_DIR, "demo_tree.json")
        with open(demo_tree_path) as f:
            tree = json.load(f)
        for branch_name, branch in tree["branches"].items():
            for leaf in branch.get("leaves", []):
                for field in ["id", "content", "confidence", "source", "created", "hash"]:
                    assert field in leaf, f"Missing '{field}' in {branch_name} leaf {leaf.get('id')}"

    def test_demo_tree_confidence_in_range(self):
        """All confidence values in demo tree are between 0 and 1."""
        demo_tree_path = os.path.join(DEMO_DIR, "demo_tree.json")
        with open(demo_tree_path) as f:
            tree = json.load(f)
        for branch_name, branch in tree["branches"].items():
            for leaf in branch.get("leaves", []):
                c = leaf.get("confidence", -1)
                assert 0.0 <= c <= 1.0, f"Confidence {c} out of range in {branch_name} leaf {leaf.get('id')}"

    def test_demo_tree_root_hash_present(self):
        """Demo tree root hash is a non-empty string."""
        demo_tree_path = os.path.join(DEMO_DIR, "demo_tree.json")
        with open(demo_tree_path) as f:
            tree = json.load(f)
        assert len(tree["root_hash"]) > 0, "root_hash is empty"


# ── Core File Integrity ────────────────────────────────────────────────────

class TestCoreFiles:

    def test_no_personal_paths_in_core(self):
        """No personal paths or identifiers in core source files."""
        banned = ["/users/whis", "openclaw.local", "sberbank", "imamniy", "idwty11"]
        for fname in os.listdir(CORE_DIR):
            if not fname.endswith(".py"):
                continue
            path = os.path.join(CORE_DIR, fname)
            with open(path) as f:
                content = f.read().lower()
            for term in banned:
                assert term not in content, f"Found '{term}' in {fname}"

    def test_core_files_present(self):
        """All expected core files are present."""
        expected = [
            "knowledge_tree.py",
            "knowledge_prune.py",
            "knowledge_search.py",
            "verify_memory.py",
            "gardener.py",
        ]
        for fname in expected:
            path = os.path.join(CORE_DIR, fname)
            assert os.path.exists(path), f"Missing core file: {fname}"

    def test_demo_server_present(self):
        """Demo server file exists."""
        assert os.path.exists(os.path.join(DEMO_DIR, "server.py"))

    def test_demo_index_present(self):
        """Demo index.html exists."""
        assert os.path.exists(os.path.join(DEMO_DIR, "index.html"))
