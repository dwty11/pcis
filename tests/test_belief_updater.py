#!/usr/bin/env python3
"""
Tests for core/belief_updater.py — Bayesian belief updating.
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(TESTS_DIR, "..")
sys.path.insert(0, ROOT_DIR)

# Set PCIS_BASE_DIR to a temp dir so tests don't touch real data.
_tmp_base = tempfile.mkdtemp()
os.environ["PCIS_BASE_DIR"] = _tmp_base

from core.belief_updater import (
    _apply_update,
    update_from_synapse,
    recompute_all,
    get_update_log,
    CONFIDENCE_MIN,
    CONFIDENCE_MAX,
)
from core.knowledge_tree import (
    hash_leaf,
    compute_branch_hash,
    compute_root_hash,
    verify_tree_integrity,
)


def _make_tree_with_leaf(leaf_id="leaf-1", confidence=0.85, content="Test belief",
                         branch="technical"):
    """Create a minimal valid tree with one leaf."""
    timestamp = "2026-01-01 00:00:00 UTC"
    leaf_hash = hash_leaf(content, branch, timestamp)
    leaf = {
        "id": leaf_id,
        "content": content,
        "confidence": confidence,
        "source": "test",
        "created": timestamp,
        "hash": leaf_hash,
    }
    tree = {
        "version": 1,
        "instance": "test",
        "last_updated": timestamp,
        "root_hash": "",
        "branches": {
            branch: {
                "hash": compute_branch_hash([leaf]),
                "leaves": [leaf],
            }
        },
    }
    tree["root_hash"] = compute_root_hash(tree)
    return tree


def _make_synapse(from_leaf, to_leaf, relation, synapse_id="syn-1"):
    return {
        "id": synapse_id,
        "from_leaf": from_leaf,
        "to_leaf": to_leaf,
        "relation": relation,
        "note": "",
        "source": "test",
        "created": "2026-01-02 00:00:00 UTC",
        "hash": hashlib.sha256(
            f"{from_leaf}+{to_leaf}+{relation}+2026-01-02 00:00:00 UTC".encode()
        ).hexdigest(),
    }


class TestApplyUpdate(unittest.TestCase):
    """Test the core Bayesian formula."""

    def test_supports_increases_confidence(self):
        """SUPPORTS: P(H|E) = P(H) + (1 - P(H)) * 0.15"""
        old = 0.85
        new = _apply_update(old, "SUPPORTS")
        expected = old + (1 - old) * 0.15  # 0.85 + 0.15 * 0.15 = 0.8725
        self.assertAlmostEqual(new, expected, places=6)
        self.assertGreater(new, old)

    def test_contradicts_decreases_confidence(self):
        """CONTRADICTS: P(H|E) = P(H) * 0.80"""
        old = 0.85
        new = _apply_update(old, "CONTRADICTS")
        expected = old * 0.80  # 0.68
        self.assertAlmostEqual(new, expected, places=6)
        self.assertLess(new, old)

    def test_other_relations_no_change(self):
        """REFINES, DERIVES_FROM, SUPERSEDES don't trigger Bayesian update."""
        for rel in ("REFINES", "DERIVES_FROM", "SUPERSEDES"):
            self.assertEqual(_apply_update(0.85, rel), 0.85)

    def test_cap_max(self):
        """Confidence never exceeds 0.98."""
        # 0.97 + 0.03*0.15 = 0.9745, still below cap. Use a value that would exceed.
        conf = 0.97
        for _ in range(20):
            conf = _apply_update(conf, "SUPPORTS")
        self.assertLessEqual(conf, CONFIDENCE_MAX)
        self.assertEqual(conf, CONFIDENCE_MAX)

    def test_cap_min(self):
        """Confidence never goes below 0.05."""
        # Repeatedly contradict to drive confidence very low
        conf = 0.1
        for _ in range(20):
            conf = _apply_update(conf, "CONTRADICTS")
        self.assertGreaterEqual(conf, CONFIDENCE_MIN)
        self.assertEqual(conf, CONFIDENCE_MIN)

    def test_supports_exact_formula(self):
        """Verify the exact formula: P + (1 - P) * 0.15"""
        for p in [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0]:
            result = _apply_update(p, "SUPPORTS")
            raw = p + (1 - p) * 0.15
            expected = max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, raw))
            self.assertAlmostEqual(result, expected, places=6,
                                   msg=f"Failed for P={p}")

    def test_contradicts_exact_formula(self):
        """Verify the exact formula: P * 0.80"""
        for p in [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0]:
            result = _apply_update(p, "CONTRADICTS")
            raw = p * 0.80
            expected = max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, raw))
            self.assertAlmostEqual(result, expected, places=6,
                                   msg=f"Failed for P={p}")


class TestUpdateFromSynapse(unittest.TestCase):
    """Test update_from_synapse() end-to-end."""

    def setUp(self):
        self.log_file = os.path.join(tempfile.mkdtemp(), "test-log.json")

    def test_supports_updates_tree(self):
        tree = _make_tree_with_leaf(confidence=0.80)
        synapse = _make_synapse("other-leaf", "leaf-1", "SUPPORTS")
        result = update_from_synapse(synapse, tree, log_file=self.log_file)

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["new_confidence"], 0.80 + 0.20 * 0.15, places=6)
        # Verify the tree was actually modified
        leaf = tree["branches"]["technical"]["leaves"][0]
        self.assertAlmostEqual(leaf["confidence"], 0.83, places=2)

    def test_contradicts_updates_tree(self):
        tree = _make_tree_with_leaf(confidence=0.80)
        synapse = _make_synapse("other-leaf", "leaf-1", "CONTRADICTS")
        result = update_from_synapse(synapse, tree, log_file=self.log_file)

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["new_confidence"], 0.64, places=6)

    def test_missing_leaf_skipped(self):
        tree = _make_tree_with_leaf(confidence=0.80)
        synapse = _make_synapse("other-leaf", "nonexistent-leaf", "SUPPORTS")
        result = update_from_synapse(synapse, tree, log_file=self.log_file)
        self.assertIsNone(result)

    def test_refines_returns_none(self):
        tree = _make_tree_with_leaf(confidence=0.80)
        synapse = _make_synapse("other-leaf", "leaf-1", "REFINES")
        result = update_from_synapse(synapse, tree, log_file=self.log_file)
        self.assertIsNone(result)

    def test_update_log_written(self):
        tree = _make_tree_with_leaf(confidence=0.80)
        synapse = _make_synapse("other-leaf", "leaf-1", "SUPPORTS")
        update_from_synapse(synapse, tree, log_file=self.log_file)

        log = get_update_log(self.log_file)
        self.assertEqual(len(log), 1)
        entry = log[0]
        self.assertEqual(entry["leaf_id"], "leaf-1")
        self.assertAlmostEqual(entry["old_confidence"], 0.80, places=6)
        self.assertIn("SUPPORTS", entry["reason"])
        self.assertIn("timestamp", entry)

    def test_log_is_append_only(self):
        tree = _make_tree_with_leaf(confidence=0.80)
        synapse1 = _make_synapse("a", "leaf-1", "SUPPORTS", synapse_id="s1")
        synapse2 = _make_synapse("b", "leaf-1", "CONTRADICTS", synapse_id="s2")

        update_from_synapse(synapse1, tree, log_file=self.log_file)
        update_from_synapse(synapse2, tree, log_file=self.log_file)

        log = get_update_log(self.log_file)
        self.assertEqual(len(log), 2)
        self.assertIn("SUPPORTS", log[0]["reason"])
        self.assertIn("CONTRADICTS", log[1]["reason"])


class TestHashChainAfterUpdate(unittest.TestCase):
    """Verify full Merkle integrity is maintained after Bayesian updates."""

    def test_tree_integrity_after_supports(self):
        tree = _make_tree_with_leaf(confidence=0.80)
        log_file = os.path.join(tempfile.mkdtemp(), "log.json")
        synapse = _make_synapse("other-leaf", "leaf-1", "SUPPORTS")
        update_from_synapse(synapse, tree, log_file=log_file)

        ok, errors = verify_tree_integrity(tree)
        self.assertTrue(ok, f"Integrity errors: {errors}")

    def test_tree_integrity_after_contradicts(self):
        tree = _make_tree_with_leaf(confidence=0.80)
        log_file = os.path.join(tempfile.mkdtemp(), "log.json")
        synapse = _make_synapse("other-leaf", "leaf-1", "CONTRADICTS")
        update_from_synapse(synapse, tree, log_file=log_file)

        ok, errors = verify_tree_integrity(tree)
        self.assertTrue(ok, f"Integrity errors: {errors}")

    def test_confidence_changes_and_integrity_holds(self):
        """Confidence changes but hash chain stays valid (confidence is metadata, not content)."""
        tree = _make_tree_with_leaf(confidence=0.80)
        conf_before = tree["branches"]["technical"]["leaves"][0]["confidence"]

        log_file = os.path.join(tempfile.mkdtemp(), "log.json")
        synapse = _make_synapse("other-leaf", "leaf-1", "SUPPORTS")
        update_from_synapse(synapse, tree, log_file=log_file)

        conf_after = tree["branches"]["technical"]["leaves"][0]["confidence"]
        self.assertNotEqual(conf_before, conf_after)
        # Integrity still valid
        ok, errors = verify_tree_integrity(tree)
        self.assertTrue(ok, f"Integrity errors: {errors}")


class TestRecomputeAll(unittest.TestCase):
    """Test recompute_all() with multiple synapses."""

    def test_recompute_with_multiple_synapses(self):
        tree = _make_tree_with_leaf(confidence=0.80)
        log_file = os.path.join(tempfile.mkdtemp(), "log.json")

        synapses = {
            "version": 1,
            "root_hash": "",
            "synapses": [
                _make_synapse("a", "leaf-1", "SUPPORTS", synapse_id="s1"),
                _make_synapse("b", "leaf-1", "CONTRADICTS", synapse_id="s2"),
            ],
        }

        result = recompute_all(tree, synapses=synapses, log_file=log_file)

        self.assertIn("updated", result)
        self.assertIn("changes", result)
        self.assertGreater(result["updated"], 0)

        # Verify the final confidence reflects both updates applied in order
        leaf = tree["branches"]["technical"]["leaves"][0]
        # Start at 0.80
        # After SUPPORTS: 0.80 + 0.20 * 0.15 = 0.83
        # After CONTRADICTS: 0.83 * 0.80 = 0.664
        self.assertAlmostEqual(leaf["confidence"], 0.664, places=3)

        # Integrity still holds
        ok, errors = verify_tree_integrity(tree)
        self.assertTrue(ok, f"Integrity errors: {errors}")

    def test_recompute_skips_missing_leaves(self):
        tree = _make_tree_with_leaf(confidence=0.80)
        log_file = os.path.join(tempfile.mkdtemp(), "log.json")

        synapses = {
            "version": 1,
            "root_hash": "",
            "synapses": [
                _make_synapse("a", "nonexistent", "SUPPORTS", synapse_id="s1"),
            ],
        }

        result = recompute_all(tree, synapses=synapses, log_file=log_file)
        self.assertEqual(result["updated"], 0)

    def test_recompute_log_entries(self):
        tree = _make_tree_with_leaf(confidence=0.80)
        log_file = os.path.join(tempfile.mkdtemp(), "log.json")

        synapses = {
            "version": 1,
            "root_hash": "",
            "synapses": [
                _make_synapse("a", "leaf-1", "SUPPORTS", synapse_id="s1"),
            ],
        }

        recompute_all(tree, synapses=synapses, log_file=log_file)
        log = get_update_log(log_file)
        self.assertTrue(len(log) >= 1)
        self.assertIn("recompute", log[-1]["reason"])


class TestConfidenceCaps(unittest.TestCase):
    """Verify caps are enforced through the full stack."""

    def test_repeated_supports_caps_at_098(self):
        tree = _make_tree_with_leaf(confidence=0.95)
        log_file = os.path.join(tempfile.mkdtemp(), "log.json")

        for i in range(10):
            synapse = _make_synapse("a", "leaf-1", "SUPPORTS", synapse_id=f"s{i}")
            update_from_synapse(synapse, tree, log_file=log_file)

        leaf = tree["branches"]["technical"]["leaves"][0]
        self.assertLessEqual(leaf["confidence"], CONFIDENCE_MAX)
        self.assertAlmostEqual(leaf["confidence"], CONFIDENCE_MAX, places=6)

    def test_repeated_contradicts_caps_at_005(self):
        tree = _make_tree_with_leaf(confidence=0.50)
        log_file = os.path.join(tempfile.mkdtemp(), "log.json")

        for i in range(50):
            synapse = _make_synapse("a", "leaf-1", "CONTRADICTS", synapse_id=f"s{i}")
            update_from_synapse(synapse, tree, log_file=log_file)

        leaf = tree["branches"]["technical"]["leaves"][0]
        self.assertGreaterEqual(leaf["confidence"], CONFIDENCE_MIN)
        self.assertAlmostEqual(leaf["confidence"], CONFIDENCE_MIN, places=6)


if __name__ == "__main__":
    unittest.main()
