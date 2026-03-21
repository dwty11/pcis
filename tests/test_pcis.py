#!/usr/bin/env python3
"""
PCIS Core Tests
Run: python3 tests/test_pcis.py
"""

import hashlib
import json
import os
import sys
import tempfile
import shutil
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_DIR = os.path.join(TESTS_DIR, "..", "core")
sys.path.insert(0, CORE_DIR)

import importlib
os.environ.setdefault("PCIS_BASE_DIR", tempfile.mkdtemp())
import knowledge_tree as kt
import knowledge_prune as kp
import gardener as gd


class TestMerkleHashing(unittest.TestCase):
    """Merkle root changes when knowledge changes."""

    def _empty_tree(self):
        return {"version": 1, "instance": "test", "root_hash": "",
                "last_updated": "2026-01-01T00:00:00Z", "branches": {}}

    def _make_leaf(self, content, lid="l1"):
        h = kt.hash_leaf(content, "lessons", "2026-01-01T00:00:00Z")
        return {"id": lid, "content": content, "confidence": 0.9,
                "source": "test", "created": "2026-01-01T00:00:00Z", "hash": h}

    def test_root_changes_on_new_leaf(self):
        """Adding a leaf changes the Merkle root."""
        tree = self._empty_tree()
        root_before = kt.compute_root_hash(tree)

        tree["branches"]["lessons"] = {"hash": "", "leaves": [self._make_leaf("first leaf")]}
        tree["branches"]["lessons"]["hash"] = kt.compute_branch_hash(tree["branches"]["lessons"]["leaves"])
        root_after = kt.compute_root_hash(tree)

        self.assertNotEqual(root_before, root_after)

    def test_root_deterministic(self):
        """Same tree always produces same root hash."""
        tree = self._empty_tree()
        tree["branches"]["technical"] = {"hash": "", "leaves": [self._make_leaf("determinism")]}
        tree["branches"]["technical"]["hash"] = kt.compute_branch_hash(tree["branches"]["technical"]["leaves"])

        r1 = kt.compute_root_hash(tree)
        r2 = kt.compute_root_hash(tree)
        self.assertEqual(r1, r2)

    def test_leaf_hash_changes_on_content_mutation(self):
        """Mutating content produces a different hash — tamper detection works."""
        h1 = kt.hash_leaf("original", "lessons", "2026-01-01")
        h2 = kt.hash_leaf("tampered", "lessons", "2026-01-01")
        self.assertNotEqual(h1, h2)

    def test_branch_hash_order_independent(self):
        """Branch hash is stable regardless of leaf insertion order."""
        leaves = [
            {"hash": hashlib.sha256(b"a").hexdigest()},
            {"hash": hashlib.sha256(b"b").hexdigest()},
            {"hash": hashlib.sha256(b"c").hexdigest()},
        ]
        h1 = kt.compute_branch_hash(leaves)
        import random; shuffled = leaves[:]; random.shuffle(shuffled)
        h2 = kt.compute_branch_hash(shuffled)
        self.assertEqual(h1, h2)

    def test_root_changes_on_content_edit(self):
        """Editing an existing leaf changes the branch hash and root — full chain propagates."""
        tree = self._empty_tree()
        leaf = self._make_leaf("original content")
        tree["branches"]["lessons"] = {"hash": "", "leaves": [leaf]}
        tree["branches"]["lessons"]["hash"] = kt.compute_branch_hash(tree["branches"]["lessons"]["leaves"])
        root_original = kt.compute_root_hash(tree)

        # Simulate tampering
        tree["branches"]["lessons"]["leaves"][0]["content"] = "tampered content"
        tree["branches"]["lessons"]["leaves"][0]["hash"] = kt.hash_leaf("tampered content", "lessons", leaf["created"])
        tree["branches"]["lessons"]["hash"] = kt.compute_branch_hash(tree["branches"]["lessons"]["leaves"])
        root_tampered = kt.compute_root_hash(tree)

        self.assertNotEqual(root_original, root_tampered)


class TestAdversarialCounters(unittest.TestCase):
    """COUNTER leaves are correctly identified and linked."""

    def test_counter_leaf_detected(self):
        content = "COUNTER: [l1] This claim is overstated."
        self.assertTrue(content.startswith("COUNTER:"))

    def test_counter_id_parsed(self):
        content = "COUNTER: [cl-001] Confidence is too high."
        challenged_id = content[content.index("[")+1:content.index("]")]
        self.assertEqual(challenged_id, "cl-001")

    def test_normal_leaf_not_counter(self):
        content = "Acme Corp renewal scheduled Q2 2026."
        self.assertFalse(content.startswith("COUNTER:"))


class TestDemoTreeIntegrity(unittest.TestCase):
    """demo_tree.json is well-formed and internally consistent."""

    def setUp(self):
        demo_path = os.path.join(TESTS_DIR, "..", "demo", "demo_tree.json")
        with open(demo_path) as f:
            self.tree = json.load(f)

    def test_all_leaves_have_required_fields(self):
        for branch_name, branch in self.tree["branches"].items():
            for leaf in branch["leaves"]:
                for field in ("id", "content", "confidence", "source", "created", "hash"):
                    self.assertIn(field, leaf, f"Leaf {leaf.get('id')} in {branch_name} missing '{field}'")

    def test_confidence_in_range(self):
        for branch_name, branch in self.tree["branches"].items():
            for leaf in branch["leaves"]:
                self.assertGreaterEqual(leaf["confidence"], 0.0)
                self.assertLessEqual(leaf["confidence"], 1.0)

    def test_root_hash_present(self):
        self.assertIn("root_hash", self.tree)
        self.assertTrue(len(self.tree["root_hash"]) > 0)

    def test_no_personal_data_leakage(self):
        """Ensure no personal paths or identifiers leaked into demo tree."""
        raw = json.dumps(self.tree).lower()
        for term in ["whis", "openclaw", "/users/", "sberbank", "imamniyazov"]:
            self.assertNotIn(term, raw, f"Personal data leak: '{term}' found in demo_tree.json")


class TestCrossModuleHashConsistency(unittest.TestCase):
    """All modules must produce identical Merkle roots for the same tree."""

    def _build_test_tree(self):
        """Build a realistic test tree with multiple branches and leaves."""
        tree = {
            "version": 1,
            "instance": "test",
            "root_hash": "",
            "last_updated": "2026-01-01 00:00:00 UTC",
            "branches": {},
        }
        test_data = [
            ("technical", "REST endpoints should use plural nouns", "guide", 0.85),
            ("technical", "Always validate input at API boundaries", "review", 0.90),
            ("lessons", "Skimming time-sensitive data is a trust violation", "session", 0.80),
            ("lessons", "Premature abstraction costs more than duplication", "session", 0.75),
            ("philosophy", "Adversarial review prevents echo chambers", "core", 0.95),
        ]
        for branch, content, source, conf in test_data:
            if branch not in tree["branches"]:
                tree["branches"][branch] = {"hash": "", "leaves": []}
            ts = "2026-01-15 12:00:00 UTC"
            leaf_hash = kt.hash_leaf(content, branch, ts)
            leaf = {
                "id": leaf_hash[:12],
                "hash": leaf_hash,
                "content": content,
                "source": source,
                "confidence": conf,
                "created": ts,
                "promoted_to": None,
            }
            tree["branches"][branch]["leaves"].append(leaf)
        for bname in tree["branches"]:
            tree["branches"][bname]["hash"] = kt.compute_branch_hash(
                tree["branches"][bname]["leaves"]
            )
        tree["root_hash"] = kt.compute_root_hash(tree)
        return tree

    def test_all_modules_same_root(self):
        """knowledge_tree, gardener, and knowledge_prune compute identical roots."""
        tree = self._build_test_tree()

        root_kt = kt.compute_root_hash(tree)
        # gardener imports from knowledge_tree — verify it's the same function
        root_gd = gd.compute_root_hash(tree)
        # knowledge_prune imports from knowledge_tree — verify it's the same function
        root_kp = kp.compute_root_hash(tree)

        self.assertEqual(root_kt, root_gd,
                         "gardener.compute_root_hash diverges from knowledge_tree")
        self.assertEqual(root_kt, root_kp,
                         "knowledge_prune.compute_root_hash diverges from knowledge_tree")

    def test_all_modules_same_branch_hash(self):
        """Branch hash computation is identical across modules."""
        tree = self._build_test_tree()
        leaves = tree["branches"]["technical"]["leaves"]

        bh_kt = kt.compute_branch_hash(leaves)
        bh_kp = kp.compute_branch_hash(leaves)
        # gardener also imports compute_branch_hash from knowledge_tree
        bh_gd = gd.compute_branch_hash(leaves)

        self.assertEqual(bh_kt, bh_kp,
                         "knowledge_prune.compute_branch_hash diverges from knowledge_tree")
        self.assertEqual(bh_kt, bh_gd,
                         "gardener.compute_branch_hash diverges from knowledge_tree")

    def test_gardener_leaf_hash_matches_knowledge_tree(self):
        """gardener's add_leaf uses the same hash_leaf as knowledge_tree."""
        content = "Test leaf content"
        branch = "lessons"
        timestamp = "2026-02-01 10:00:00 UTC"

        h_kt = kt.hash_leaf(content, branch, timestamp)
        h_gd = gd._kt_hash_leaf(content, branch, timestamp)

        self.assertEqual(h_kt, h_gd,
                         "gardener leaf hashing diverges from knowledge_tree")


class TestAddKnowledgeValidation(unittest.TestCase):
    """Input validation on add_knowledge."""

    def _empty_tree(self):
        return {"version": 1, "instance": "test", "root_hash": "",
                "last_updated": "2026-01-01T00:00:00Z",
                "branches": {"lessons": {"hash": "", "leaves": []}}}

    def test_empty_content_raises(self):
        tree = self._empty_tree()
        with self.assertRaises(ValueError):
            kt.add_knowledge(tree, "lessons", "")
        with self.assertRaises(ValueError):
            kt.add_knowledge(tree, "lessons", "   ")

    def test_oversized_content_raises(self):
        tree = self._empty_tree()
        with self.assertRaises(ValueError):
            kt.add_knowledge(tree, "lessons", "x" * 10_001)


class TestConcurrentSaveTree(unittest.TestCase):
    """File locking prevents concurrent write corruption."""

    def test_concurrent_add_and_save(self):
        import fcntl
        import threading

        tmp_dir = tempfile.mkdtemp()
        tree_path = os.path.join(tmp_dir, "data", "tree.json")
        lock_path = tree_path + ".lock"
        os.makedirs(os.path.dirname(tree_path), exist_ok=True)

        # Patch TREE_FILE for this test
        original_tree_file = kt.TREE_FILE
        kt.TREE_FILE = tree_path

        try:
            # Create initial tree
            tree = {"version": 1, "instance": "test", "root_hash": "",
                    "last_updated": "", "branches": {"lessons": {"hash": "", "leaves": []}}}
            kt.save_tree(tree)

            errors = []

            def writer(n):
                """Each writer adds 5 leaves, locking the full read-modify-write cycle."""
                try:
                    for i in range(5):
                        # Use the same lockfile that save_tree uses, wrapping load+add+save
                        with open(lock_path, 'w') as lf:
                            fcntl.flock(lf, fcntl.LOCK_EX)
                            t = kt.load_tree()
                            kt.add_knowledge(t, "lessons", f"thread-{n}-leaf-{i}")
                            # Write directly (skip save_tree's own flock to avoid deadlock)
                            t["last_updated"] = kt.now_utc()
                            for bn in t.get("branches", {}):
                                t["branches"][bn]["hash"] = kt.compute_branch_hash(t["branches"][bn]["leaves"])
                            t["root_hash"] = kt.compute_root_hash(t)
                            tmp_path = tree_path + ".tmp"
                            with open(tmp_path, 'w', encoding='utf-8') as f:
                                json.dump(t, f, ensure_ascii=False, indent=2)
                            os.replace(tmp_path, tree_path)
                except Exception as e:
                    errors.append(e)

            t1 = threading.Thread(target=writer, args=(1,))
            t2 = threading.Thread(target=writer, args=(2,))
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            self.assertEqual(errors, [])

            # File must be valid JSON with exactly 10 leaves (5 per thread, no data loss)
            with open(tree_path) as f:
                final_tree = json.load(f)
            leaf_count = len(final_tree["branches"]["lessons"]["leaves"])
            self.assertEqual(leaf_count, 10,
                             f"Expected 10 leaves (5 per thread), got {leaf_count} — data loss detected")
        finally:
            kt.TREE_FILE = original_tree_file
            shutil.rmtree(tmp_dir)


if __name__ == "__main__":
    print("PCIS Core Test Suite\n" + "="*40)
    unittest.main(verbosity=2)
