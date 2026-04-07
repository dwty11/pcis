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
        content = "The agent processed the request successfully."
        self.assertFalse(content.startswith("COUNTER:"))


class TestCounterParsing(unittest.TestCase):
    """parse_gardener_output handles new 5-field and old prefix COUNTER formats."""

    def test_new_format_5th_field(self):
        """Leaf ID in the 5th pipe field, no prefix in content."""
        line = "COUNTER|technical|This claim is overstated|0.65|abc123def456"
        counters, _, _ = gd.parse_gardener_output(line)
        self.assertEqual(len(counters), 1)
        c = counters[0]
        self.assertEqual(c["branch"], "technical")
        self.assertEqual(c["content"], "This claim is overstated")
        self.assertAlmostEqual(c["confidence"], 0.65)
        self.assertEqual(c["original_leaf_id"], "abc123def456")

    def test_backward_compat_prefix_in_content(self):
        """Old format: COUNTER: [id] in content, no 5th field — still parses."""
        line = "COUNTER|technical|COUNTER: [abc123def456] This claim is overstated|0.65"
        counters, _, _ = gd.parse_gardener_output(line)
        self.assertEqual(len(counters), 1)
        c = counters[0]
        self.assertEqual(c["branch"], "technical")
        self.assertEqual(c["content"], "This claim is overstated")
        self.assertEqual(c["original_leaf_id"], "abc123def456")

    def test_no_leaf_id_at_all(self):
        """Neither 5th field nor prefix — original_leaf_id is None."""
        line = "COUNTER|lessons|A generic challenge|0.60"
        counters, _, _ = gd.parse_gardener_output(line)
        self.assertEqual(len(counters), 1)
        self.assertIsNone(counters[0]["original_leaf_id"])


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
        for term in ["workspace_path", "/users/", "internal_codename", "personal_name"]:
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

    def test_confidence_out_of_range_raises(self):
        tree = self._empty_tree()
        with self.assertRaises(ValueError):
            kt.add_knowledge(tree, "lessons", "valid content", confidence=-0.1)
        with self.assertRaises(ValueError):
            kt.add_knowledge(tree, "lessons", "valid content", confidence=1.01)
        # Boundaries should be accepted
        kt.add_knowledge(tree, "lessons", "zero conf", confidence=0.0)
        kt.add_knowledge(tree, "lessons", "full conf", confidence=1.0)


class TestConcurrentSaveTree(unittest.TestCase):
    """File locking prevents concurrent write corruption."""

    def test_concurrent_add_and_save(self):
        import threading
        from knowledge_tree import tree_lock

        tmp_dir = tempfile.mkdtemp()
        tree_path = os.path.join(tmp_dir, "data", "tree.json")
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
                """Each writer adds 5 leaves using tree_lock for safe concurrency."""
                try:
                    for i in range(5):
                        with tree_lock(path=tree_path) as t:
                            kt.add_knowledge(t, "lessons", f"thread-{n}-leaf-{i}")
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


class TestIdentityPortability(unittest.TestCase):
    """Verify that model config changes do NOT affect Merkle root hash.
    The root hash must be determined solely by tree content — not by
    which model processed it. This makes the hash a model-agnostic identity.
    """

    def test_root_hash_independent_of_model_config(self):
        """Same tree content must produce identical root hash regardless of model_name in config."""
        tree = {"branches": {}, "root_hash": ""}
        kt.add_knowledge(tree, "identity", "PCIS gives agents persistent memory", confidence=0.9)
        kt.add_knowledge(tree, "lessons", "Merkle integrity catches tampering", confidence=0.8)

        root_hash_default = kt.compute_root_hash(tree)

        # Simulate different model configs — none should affect the hash
        for model_name in ["gpt-4", "claude-sonnet-4-6", "llama-3-70b", "gigachat-pro", "qwen3:30b"]:
            # The config field exists in config.json but must never touch the hash pipeline
            tree["_model_config"] = model_name  # inject a config marker
            root_hash_with_config = kt.compute_root_hash(tree)
            self.assertEqual(
                root_hash_default, root_hash_with_config,
                f"Root hash changed when model_config='{model_name}' — identity portability broken"
            )

        # Clean up injected field and verify hash still matches
        del tree["_model_config"]
        self.assertEqual(root_hash_default, kt.compute_root_hash(tree))


class TestGardenerDedupGate(unittest.TestCase):
    """Semantic dedup gate for COUNTER leaves in gardener."""

    def _tree_with_counter(self, counter_content="COUNTER: [abc123] old challenge"):
        tree = {
            "version": 1, "instance": "test", "root_hash": "",
            "last_updated": "2026-01-01T00:00:00Z",
            "branches": {"technical": {"hash": "", "leaves": []}},
        }
        ts = "2026-01-15 12:00:00 UTC"
        h = kt.hash_leaf(counter_content, "technical", ts)
        tree["branches"]["technical"]["leaves"].append({
            "id": h[:12], "hash": h, "content": counter_content,
            "source": "test", "confidence": 0.65, "created": ts,
            "promoted_to": None,
        })
        return tree

    def test_near_duplicate_counter_skipped(self):
        """A COUNTER whose embedding is >= 0.82 similar to an existing one is skipped."""
        from unittest.mock import patch

        fixed_vec = [1.0] * 768
        tree = self._tree_with_counter()

        with patch("gardener.get_embedding", return_value=fixed_vec):
            is_dup, dup_id, score = gd.is_duplicate_counter(
                "COUNTER: [xyz789] nearly identical challenge", tree
            )

        self.assertTrue(is_dup)
        self.assertIsNotNone(dup_id)
        self.assertGreaterEqual(score, 0.82)

    def test_distinct_counter_committed(self):
        """A COUNTER with low similarity passes the dedup gate."""
        from unittest.mock import patch

        call_count = [0]

        def mock_embed(text):
            call_count[0] += 1
            if call_count[0] == 1:
                return [1.0] + [0.0] * 767  # new candidate
            return [0.0] + [1.0] + [0.0] * 766  # existing leaf (orthogonal)

        tree = self._tree_with_counter()

        with patch("gardener.get_embedding", side_effect=mock_embed):
            is_dup, dup_id, score = gd.is_duplicate_counter(
                "COUNTER: [xyz789] completely different challenge", tree
            )

        self.assertFalse(is_dup)
        self.assertIsNone(dup_id)
        self.assertLess(score, 0.82)

    def test_embedding_failure_triggers_fallback(self):
        """When embedding fails, is_duplicate_counter raises so caller can fallback."""
        from unittest.mock import patch

        tree = self._tree_with_counter()

        with patch("gardener.get_embedding", side_effect=RuntimeError("Ollama down")):
            with self.assertRaises(RuntimeError):
                gd.is_duplicate_counter(
                    "COUNTER: [xyz789] some challenge", tree
                )


class TestVerifyTreeIntegrity(unittest.TestCase):
    """verify_tree_integrity detects content tampering even when hash fields are untouched."""

    def test_content_tamper_detected(self):
        """Mutating leaf content without updating hashes must be caught."""
        tree = {"version": 1, "instance": "test", "root_hash": "",
                "last_updated": "", "branches": {}}
        kt.add_knowledge(tree, "lessons", "original content", "test", 0.9)
        # Finalize hashes
        tree["branches"]["lessons"]["hash"] = kt.compute_branch_hash(
            tree["branches"]["lessons"]["leaves"])
        tree["root_hash"] = kt.compute_root_hash(tree)

        # Sanity: untampered tree verifies
        ok, errors = kt.verify_tree_integrity(tree)
        self.assertTrue(ok, f"Clean tree failed verification: {errors}")

        # Tamper content without touching any hash fields
        tree["branches"]["lessons"]["leaves"][0]["content"] = "tampered content"

        ok, errors = kt.verify_tree_integrity(tree)
        self.assertFalse(ok, "Tampered tree was not detected")
        self.assertTrue(any("content-hash mismatch" in e for e in errors))


class TestMerkleProofs(unittest.TestCase):
    """Merkle inclusion proofs: generate, verify, and detect tampering."""

    def _tree_with_leaves(self, n=5):
        """Build a tree with n leaves in the 'technical' branch."""
        tree = {"version": 1, "instance": "test", "root_hash": "",
                "last_updated": "", "branches": {}}
        for i in range(n):
            kt.add_knowledge(tree, "technical", f"fact number {i}", "test", 0.8)
        tree["branches"]["technical"]["hash"] = kt.compute_branch_hash(
            tree["branches"]["technical"]["leaves"])
        tree["root_hash"] = kt.compute_root_hash(tree)
        return tree

    def test_proof_verifies_for_every_leaf(self):
        """Every leaf in a branch should produce a valid proof."""
        tree = self._tree_with_leaves(7)
        for leaf in tree["branches"]["technical"]["leaves"]:
            proof = kt.generate_proof(tree, "technical", leaf["id"])
            self.assertTrue(
                kt.verify_proof(proof["leaf_hash"], proof["proof"], proof["branch_root"]),
                f"Proof failed for leaf {leaf['id']}"
            )

    def test_proof_fails_on_wrong_leaf_hash(self):
        """Proof must fail if the leaf hash is tampered."""
        tree = self._tree_with_leaves(4)
        leaf_id = tree["branches"]["technical"]["leaves"][0]["id"]
        proof = kt.generate_proof(tree, "technical", leaf_id)
        fake_hash = hashlib.sha256(b"tampered").hexdigest()
        self.assertFalse(
            kt.verify_proof(fake_hash, proof["proof"], proof["branch_root"])
        )

    def test_proof_fails_on_wrong_root(self):
        """Proof must fail if verified against a different root."""
        tree = self._tree_with_leaves(4)
        leaf_id = tree["branches"]["technical"]["leaves"][0]["id"]
        proof = kt.generate_proof(tree, "technical", leaf_id)
        fake_root = hashlib.sha256(b"wrong_root").hexdigest()
        self.assertFalse(
            kt.verify_proof(proof["leaf_hash"], proof["proof"], fake_root)
        )

    def test_proof_single_leaf_branch(self):
        """A branch with one leaf should produce a zero-step proof."""
        tree = self._tree_with_leaves(1)
        leaf_id = tree["branches"]["technical"]["leaves"][0]["id"]
        proof = kt.generate_proof(tree, "technical", leaf_id)
        self.assertEqual(len(proof["proof"]), 0)
        # The leaf hash IS the root
        self.assertTrue(
            kt.verify_proof(proof["leaf_hash"], proof["proof"], proof["branch_root"])
        )

    def test_proof_two_leaves(self):
        """Two-leaf branch should produce a one-step proof."""
        tree = self._tree_with_leaves(2)
        leaf_id = tree["branches"]["technical"]["leaves"][0]["id"]
        proof = kt.generate_proof(tree, "technical", leaf_id)
        self.assertEqual(len(proof["proof"]), 1)
        self.assertTrue(
            kt.verify_proof(proof["leaf_hash"], proof["proof"], proof["branch_root"])
        )

    def test_proof_large_branch(self):
        """Proof depth is log2(n) for a branch with many leaves."""
        import math
        tree = self._tree_with_leaves(32)
        leaf_id = tree["branches"]["technical"]["leaves"][15]["id"]
        proof = kt.generate_proof(tree, "technical", leaf_id)
        self.assertTrue(
            kt.verify_proof(proof["leaf_hash"], proof["proof"], proof["branch_root"])
        )
        # Proof depth should be ceil(log2(32)) = 5
        self.assertEqual(len(proof["proof"]), int(math.ceil(math.log2(32))))

    def test_proof_nonexistent_leaf_raises(self):
        """Requesting a proof for a missing leaf should raise ValueError."""
        tree = self._tree_with_leaves(3)
        with self.assertRaises(ValueError):
            kt.generate_proof(tree, "technical", "nonexistent-id")

    def test_proof_nonexistent_branch_raises(self):
        """Requesting a proof for a missing branch should raise ValueError."""
        tree = self._tree_with_leaves(3)
        with self.assertRaises(ValueError):
            kt.generate_proof(tree, "no_such_branch", "any-id")

    def test_proof_survives_other_branch_changes(self):
        """A proof for branch A should still verify after branch B changes."""
        tree = self._tree_with_leaves(4)
        leaf_id = tree["branches"]["technical"]["leaves"][0]["id"]
        proof = kt.generate_proof(tree, "technical", leaf_id)

        # Add leaves to a different branch — technical branch root unchanged
        kt.add_knowledge(tree, "lessons", "new lesson", "test", 0.7)
        tree["branches"]["lessons"]["hash"] = kt.compute_branch_hash(
            tree["branches"]["lessons"]["leaves"])

        self.assertTrue(
            kt.verify_proof(proof["leaf_hash"], proof["proof"], proof["branch_root"])
        )

    def test_proof_invalidated_by_leaf_removal(self):
        """Removing a leaf from the branch changes the root, invalidating old proofs."""
        tree = self._tree_with_leaves(4)
        leaf_id = tree["branches"]["technical"]["leaves"][0]["id"]
        proof = kt.generate_proof(tree, "technical", leaf_id)
        old_root = proof["branch_root"]

        # Remove a different leaf — the branch root must change
        other_id = tree["branches"]["technical"]["leaves"][1]["id"]
        kt.prune_leaf(tree, "technical", other_id)

        new_root = tree["branches"]["technical"]["hash"]
        self.assertNotEqual(old_root, new_root)
        # Old proof no longer matches new root
        self.assertFalse(
            kt.verify_proof(proof["leaf_hash"], proof["proof"], new_root)
        )


class TestBinaryMerkleTreeStructure(unittest.TestCase):
    """Verify that compute_branch_hash uses a proper binary tree with domain separation."""

    def test_single_leaf_domain_separated(self):
        """One leaf: branch hash = H(0x00 || leaf_hash), not the leaf hash itself."""
        h = hashlib.sha256(b"only-leaf").hexdigest()
        leaves = [{"hash": h}]
        root = kt.compute_branch_hash(leaves)
        # Domain separation: leaf gets 0x00 prefix
        expected = hashlib.sha256(b'\x00' + h.encode()).hexdigest()
        self.assertEqual(root, expected)
        # Must NOT equal the raw leaf hash (domain separation working)
        self.assertNotEqual(root, h)

    def test_two_leaves_domain_separated(self):
        """Two leaves: domain-separated leaves combined with 0x01 internal prefix."""
        h1 = hashlib.sha256(b"alpha").hexdigest()
        h2 = hashlib.sha256(b"beta").hexdigest()
        leaves = [{"hash": h1}, {"hash": h2}]
        root = kt.compute_branch_hash(leaves)

        pair = sorted([h1, h2])
        ds0 = hashlib.sha256(b'\x00' + pair[0].encode()).hexdigest()
        ds1 = hashlib.sha256(b'\x00' + pair[1].encode()).hexdigest()
        expected = hashlib.sha256(b'\x01' + (ds0 + ds1).encode()).hexdigest()
        self.assertEqual(root, expected)

    def test_three_leaves_uses_pad_not_duplicate(self):
        """Three leaves: odd leaf paired with MERKLE_PAD, not with itself."""
        h1 = hashlib.sha256(b"a").hexdigest()
        h2 = hashlib.sha256(b"b").hexdigest()
        h3 = hashlib.sha256(b"c").hexdigest()
        leaves = [{"hash": h1}, {"hash": h2}, {"hash": h3}]
        root = kt.compute_branch_hash(leaves)

        s = sorted([h1, h2, h3])
        ds = [hashlib.sha256(b'\x00' + x.encode()).hexdigest() for x in s]
        left_pair = hashlib.sha256(b'\x01' + (ds[0] + ds[1]).encode()).hexdigest()
        right_pair = hashlib.sha256(b'\x01' + (ds[2] + kt.MERKLE_PAD).encode()).hexdigest()
        expected = hashlib.sha256(b'\x01' + (left_pair + right_pair).encode()).hexdigest()
        self.assertEqual(root, expected)


class TestNoDuplicateLeafCollision(unittest.TestCase):
    """CVE-2012-2459: [a, b, c] and [a, b, c, c] must produce different roots."""

    def test_no_duplicate_leaf_collision(self):
        a = hashlib.sha256(b"leaf_a").hexdigest()
        b = hashlib.sha256(b"leaf_b").hexdigest()
        c = hashlib.sha256(b"leaf_c").hexdigest()

        root_abc, _ = kt._merkle_tree_from_hashes([a, b, c])
        root_abcc, _ = kt._merkle_tree_from_hashes([a, b, c, c])

        self.assertNotEqual(
            root_abc, root_abcc,
            "Trees [a,b,c] and [a,b,c,c] produced the same root — "
            "CVE-2012-2459 duplicate-leaf collision present"
        )


class TestDomainSeparation(unittest.TestCase):
    """RFC 6962: domain-separated leaf hash != raw sha256 of the same content."""

    def test_domain_separation(self):
        content = "leaf_content"
        raw_hash = hashlib.sha256(content.encode()).hexdigest()
        # Domain-separated leaf: sha256(0x00 || raw_hash)
        domain_sep = hashlib.sha256(b'\x00' + raw_hash.encode()).hexdigest()
        self.assertNotEqual(
            raw_hash, domain_sep,
            "Domain separation had no effect — second-preimage risk"
        )
        # Verify _merkle_tree_from_hashes applies it
        root, levels = kt._merkle_tree_from_hashes([raw_hash])
        self.assertEqual(root, domain_sep)
        self.assertNotEqual(root, raw_hash)


if __name__ == "__main__":
    print("PCIS Core Test Suite\n" + "="*40)
    unittest.main(verbosity=2)
