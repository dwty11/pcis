#!/usr/bin/env python3
"""
Tests for core/belief_history.py — version history for knowledge leaves.
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

_tmp_base = tempfile.mkdtemp()
os.environ.setdefault("PCIS_BASE_DIR", _tmp_base)

from core.belief_history import (
    record_change,
    get_leaf_history,
    get_recent_changes,
    diff_versions,
    VALID_CHANGE_TYPES,
    _load_history,
)
from core.knowledge_tree import (
    hash_leaf,
    compute_branch_hash,
    compute_root_hash,
)


def _make_tree(leaf_id="leaf-1", confidence=0.85, content="Test belief",
               branch="technical"):
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


class TestRecordChange(unittest.TestCase):
    """Test record_change() writes correct format."""

    def setUp(self):
        self.history_file = os.path.join(tempfile.mkdtemp(), "history.json")
        self.tree = _make_tree()

    def test_writes_correct_format(self):
        rec = record_change(
            "leaf-1", "confidence_update", 0.85, 0.90,
            "SUPPORTS synapse abc", self.tree,
            history_file=self.history_file,
        )
        self.assertEqual(rec["leaf_id"], "leaf-1")
        self.assertEqual(rec["change_type"], "confidence_update")
        self.assertEqual(rec["old_value"], 0.85)
        self.assertEqual(rec["new_value"], 0.90)
        self.assertEqual(rec["reason"], "SUPPORTS synapse abc")
        self.assertIn("timestamp", rec)
        self.assertIn("leaf_hash_before", rec)
        self.assertIn("leaf_hash_after", rec)

    def test_all_valid_change_types(self):
        for ct in VALID_CHANGE_TYPES:
            hf = os.path.join(tempfile.mkdtemp(), "h.json")
            rec = record_change(
                "leaf-1", ct, "old", "new", "test", self.tree,
                history_file=hf,
            )
            self.assertEqual(rec["change_type"], ct)

    def test_invalid_change_type_raises(self):
        with self.assertRaises(ValueError):
            record_change(
                "leaf-1", "bogus_type", "old", "new", "test", self.tree,
                history_file=self.history_file,
            )

    def test_record_persisted_to_file(self):
        record_change(
            "leaf-1", "created", None, 0.85, "initial", self.tree,
            history_file=self.history_file,
        )
        raw = _load_history(self.history_file)
        self.assertEqual(len(raw), 1)
        self.assertEqual(raw[0]["leaf_id"], "leaf-1")

    def test_leaf_hash_captured_for_confidence_update(self):
        rec = record_change(
            "leaf-1", "confidence_update", 0.85, 0.90,
            "test", self.tree, history_file=self.history_file,
        )
        # For confidence updates, hash doesn't change
        self.assertEqual(rec["leaf_hash_before"], rec["leaf_hash_after"])
        self.assertTrue(len(rec["leaf_hash_after"]) > 0)


class TestGetLeafHistory(unittest.TestCase):
    """Test get_leaf_history() returns correct records."""

    def setUp(self):
        self.history_file = os.path.join(tempfile.mkdtemp(), "history.json")
        self.tree = _make_tree()

    def test_returns_records_for_leaf(self):
        record_change("leaf-1", "created", None, 0.85, "init", self.tree,
                       history_file=self.history_file)
        record_change("leaf-1", "confidence_update", 0.85, 0.90, "test", self.tree,
                       history_file=self.history_file)
        record_change("leaf-2", "created", None, 0.70, "init", self.tree,
                       history_file=self.history_file)

        history = get_leaf_history("leaf-1", history_file=self.history_file)
        self.assertEqual(len(history), 2)
        self.assertTrue(all(r["leaf_id"] == "leaf-1" for r in history))

    def test_returns_empty_for_unknown_leaf(self):
        history = get_leaf_history("nonexistent", history_file=self.history_file)
        self.assertEqual(history, [])

    def test_chronological_order(self):
        record_change("leaf-1", "created", None, 0.85, "first", self.tree,
                       history_file=self.history_file)
        record_change("leaf-1", "confidence_update", 0.85, 0.90, "second", self.tree,
                       history_file=self.history_file)

        history = get_leaf_history("leaf-1", history_file=self.history_file)
        self.assertEqual(history[0]["reason"], "first")
        self.assertEqual(history[1]["reason"], "second")


class TestGetRecentChanges(unittest.TestCase):
    """Test get_recent_changes() respects N limit and ordering."""

    def setUp(self):
        self.history_file = os.path.join(tempfile.mkdtemp(), "history.json")
        self.tree = _make_tree()

    def test_respects_n_limit(self):
        for i in range(10):
            record_change("leaf-1", "confidence_update", 0.5 + i * 0.01,
                           0.5 + (i + 1) * 0.01, f"change-{i}", self.tree,
                           history_file=self.history_file)

        recent = get_recent_changes(n=5, history_file=self.history_file)
        self.assertEqual(len(recent), 5)

    def test_newest_first(self):
        record_change("leaf-1", "created", None, 0.85, "first", self.tree,
                       history_file=self.history_file)
        record_change("leaf-1", "confidence_update", 0.85, 0.90, "second", self.tree,
                       history_file=self.history_file)

        recent = get_recent_changes(n=10, history_file=self.history_file)
        # newest first
        self.assertEqual(recent[0]["reason"], "second")
        self.assertEqual(recent[1]["reason"], "first")

    def test_empty_returns_empty(self):
        recent = get_recent_changes(n=10, history_file=self.history_file)
        self.assertEqual(recent, [])

    def test_n_larger_than_total(self):
        record_change("leaf-1", "created", None, 0.85, "only", self.tree,
                       history_file=self.history_file)
        recent = get_recent_changes(n=100, history_file=self.history_file)
        self.assertEqual(len(recent), 1)


class TestDiffVersions(unittest.TestCase):
    """Test diff_versions() returns correct diff."""

    def setUp(self):
        self.history_file = os.path.join(tempfile.mkdtemp(), "history.json")
        self.tree = _make_tree()

    def test_diff_two_versions(self):
        record_change("leaf-1", "created", None, 0.85, "initial", self.tree,
                       history_file=self.history_file)
        record_change("leaf-1", "confidence_update", 0.85, 0.90, "bump", self.tree,
                       history_file=self.history_file)

        result = diff_versions("leaf-1", 0, 1, history_file=self.history_file)
        self.assertEqual(result["leaf_id"], "leaf-1")
        self.assertEqual(result["v1_index"], 0)
        self.assertEqual(result["v2_index"], 1)
        self.assertIn("v1", result)
        self.assertIn("v2", result)
        self.assertIn("changes", result)
        self.assertEqual(result["v1"]["reason"], "initial")
        self.assertEqual(result["v2"]["reason"], "bump")
        # changes dict has paired values
        self.assertEqual(result["changes"]["reason"], ["initial", "bump"])

    def test_diff_no_history(self):
        result = diff_versions("nonexistent", 0, 1, history_file=self.history_file)
        self.assertIn("error", result)

    def test_diff_out_of_range(self):
        record_change("leaf-1", "created", None, 0.85, "only", self.tree,
                       history_file=self.history_file)
        result = diff_versions("leaf-1", 0, 5, history_file=self.history_file)
        self.assertIn("error", result)

    def test_diff_same_version(self):
        record_change("leaf-1", "created", None, 0.85, "only", self.tree,
                       history_file=self.history_file)
        result = diff_versions("leaf-1", 0, 0, history_file=self.history_file)
        self.assertEqual(result["v1"]["reason"], result["v2"]["reason"])


class TestAppendOnly(unittest.TestCase):
    """Test that existing records are never modified."""

    def setUp(self):
        self.history_file = os.path.join(tempfile.mkdtemp(), "history.json")
        self.tree = _make_tree()

    def test_existing_records_preserved(self):
        record_change("leaf-1", "created", None, 0.85, "first", self.tree,
                       history_file=self.history_file)

        # Snapshot first record
        history1 = _load_history(self.history_file)
        first_record = dict(history1[0])

        # Add more records
        record_change("leaf-1", "confidence_update", 0.85, 0.90, "second", self.tree,
                       history_file=self.history_file)
        record_change("leaf-2", "created", None, 0.70, "third", self.tree,
                       history_file=self.history_file)

        # Verify first record unchanged
        history2 = _load_history(self.history_file)
        self.assertEqual(len(history2), 3)
        self.assertEqual(history2[0], first_record)


class TestIntegrationWithUpdater(unittest.TestCase):
    """Test that belief_updater triggers history recording automatically."""

    def test_update_from_synapse_records_history(self):
        from core.belief_updater import update_from_synapse

        tree = _make_tree(confidence=0.80)
        log_file = os.path.join(tempfile.mkdtemp(), "log.json")
        history_file = os.path.join(tempfile.mkdtemp(), "history.json")

        synapse = {
            "id": "syn-test",
            "from_leaf": "other",
            "to_leaf": "leaf-1",
            "relation": "SUPPORTS",
            "note": "",
            "source": "test",
            "created": "2026-01-02 00:00:00 UTC",
            "hash": hashlib.sha256(b"test").hexdigest(),
        }
        update_from_synapse(synapse, tree, log_file=log_file,
                            history_file=history_file)

        history = get_leaf_history("leaf-1", history_file=history_file)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["change_type"], "confidence_update")
        self.assertAlmostEqual(history[0]["old_value"], 0.80, places=6)
        self.assertIn("SUPPORTS", history[0]["reason"])


if __name__ == "__main__":
    unittest.main()
