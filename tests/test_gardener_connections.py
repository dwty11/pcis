#!/usr/bin/env python3
"""Tests for gardener_connections.py"""

import json
import os
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_DIR = os.path.join(TESTS_DIR, "..", "core")
sys.path.insert(0, CORE_DIR)

_tmpdir = tempfile.mkdtemp()
os.environ["PCIS_BASE_DIR"] = _tmpdir
os.makedirs(os.path.join(_tmpdir, "data"), exist_ok=True)

import gardener_connections as gc


class TestPairKey(unittest.TestCase):
    """pair_key should be order-independent."""

    def test_pair_key_order_independent(self):
        self.assertEqual(gc.pair_key("aaa", "bbb"), gc.pair_key("bbb", "aaa"))

    def test_pair_key_deterministic(self):
        self.assertEqual(gc.pair_key("x", "y"), gc.pair_key("x", "y"))

    def test_pair_key_contains_both_ids(self):
        key = gc.pair_key("leaf1", "leaf2")
        self.assertIn("leaf1", key)
        self.assertIn("leaf2", key)


class TestGetAllLeaves(unittest.TestCase):
    """get_all_leaves should filter stubs and short content."""

    def _make_tree(self, leaves_by_branch):
        tree = {"branches": {}}
        for branch, leaves in leaves_by_branch.items():
            tree["branches"][branch] = {
                "hash": "",
                "leaves": [
                    {"id": f"id-{i}", "content": c, "confidence": 0.8, "source": "test"}
                    for i, c in enumerate(leaves)
                ],
            }
        return tree

    def test_skips_short_content(self):
        tree = self._make_tree({"tech": ["short", "x" * 100]})
        leaves = gc.get_all_leaves(tree)
        self.assertEqual(len(leaves), 1)
        self.assertEqual(leaves[0]["id"], "id-1")

    def test_skips_stub_content(self):
        tree = self._make_tree({"tech": ["COUNTER:", "SYNAPSE:", "x" * 100]})
        leaves = gc.get_all_leaves(tree)
        self.assertEqual(len(leaves), 1)

    def test_skips_excluded_branches(self):
        tree = self._make_tree({
            "constraints": ["x" * 100],
            "rules": ["x" * 100],
            "tech": ["x" * 100],
        })
        leaves = gc.get_all_leaves(tree)
        # Only tech branch should appear
        branches = {l["branch"] for l in leaves}
        self.assertEqual(branches, {"tech"})

    def test_content_truncated_to_200(self):
        tree = self._make_tree({"tech": ["x" * 500]})
        leaves = gc.get_all_leaves(tree)
        self.assertEqual(len(leaves[0]["content"]), 200)


class TestExistingSynapsePairs(unittest.TestCase):

    def test_extracts_pairs(self):
        data = {
            "synapses": [
                {"from_leaf": "a", "to_leaf": "b", "relation": "SUPPORTS"},
                {"from_leaf": "c", "to_leaf": "d", "relation": "CONTRADICTS"},
            ]
        }
        pairs = gc.existing_synapse_pairs(data)
        self.assertIn(gc.pair_key("a", "b"), pairs)
        self.assertIn(gc.pair_key("c", "d"), pairs)
        self.assertEqual(len(pairs), 2)


class TestSynapseRecord(unittest.TestCase):

    def test_add_synapse_record(self):
        data = {"synapses": []}
        synapse = gc.add_synapse_record(data, "leaf1", "leaf2", "SUPPORTS", "test note")
        self.assertEqual(len(data["synapses"]), 1)
        self.assertEqual(synapse["from_leaf"], "leaf1")
        self.assertEqual(synapse["relation"], "SUPPORTS")
        self.assertIn("id", synapse)
        self.assertIn("hash", synapse)

    def test_find_synapse_by_pair(self):
        data = {"synapses": [
            {"from_leaf": "a", "to_leaf": "b", "relation": "SUPPORTS"},
        ]}
        found = gc.find_synapse_by_pair(data, "b", "a")
        self.assertIsNotNone(found)

    def test_find_synapse_by_pair_not_found(self):
        data = {"synapses": [
            {"from_leaf": "a", "to_leaf": "b", "relation": "SUPPORTS"},
        ]}
        found = gc.find_synapse_by_pair(data, "x", "y")
        self.assertIsNone(found)

    def test_update_synapse(self):
        synapse = {"from_leaf": "a", "to_leaf": "b", "relation": "SUPPORTS",
                    "note": "old", "created": "old", "hash": "old"}
        gc.update_synapse(synapse, "CONTRADICTS", "new note")
        self.assertEqual(synapse["relation"], "CONTRADICTS")
        self.assertEqual(synapse["note"], "new note")
        self.assertNotEqual(synapse["hash"], "old")


class TestScannedPersistence(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig = gc.SCANNED_FILE
        gc.SCANNED_FILE = os.path.join(self.tmpdir, "scanned.json")

    def tearDown(self):
        gc.SCANNED_FILE = self._orig

    def test_save_and_load_scanned(self):
        scanned = {"a-b", "c-d"}
        gc.save_scanned(scanned)
        loaded = gc.load_scanned()
        self.assertEqual(loaded, scanned)

    def test_load_scanned_empty(self):
        loaded = gc.load_scanned()
        self.assertEqual(loaded, set())


if __name__ == "__main__":
    unittest.main()
