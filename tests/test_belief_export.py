"""Tests for .belief export/import (export_belief / load_belief)."""

import os
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_DIR = os.path.join(TESTS_DIR, "..", "core")
sys.path.insert(0, CORE_DIR)

os.environ.setdefault("PCIS_BASE_DIR", tempfile.mkdtemp())

import knowledge_tree as kt  # noqa: E402


class TestExtractKeywords(unittest.TestCase):
    def test_basic(self):
        kw = kt._extract_keywords("REST endpoints should use plural nouns")
        self.assertEqual(kw, "REST,endpoints,use")

    def test_filters_stop_words(self):
        kw = kt._extract_keywords("the quick brown fox")
        self.assertNotIn("the", kw.split(","))

    def test_empty(self):
        self.assertEqual(kt._extract_keywords(""), "")


class TestLeafFlags(unittest.TestCase):
    def test_core_flag(self):
        self.assertIn("CORE", kt._leaf_flags("important fact", 0.95))

    def test_counter_flag(self):
        self.assertIn("COUNTER", kt._leaf_flags("COUNTER: not actually true", 0.5))

    def test_both_flags(self):
        flags = kt._leaf_flags("COUNTER: very confident counter", 0.95)
        self.assertIn("CORE", flags)
        self.assertIn("COUNTER", flags)

    def test_no_flags(self):
        self.assertEqual(kt._leaf_flags("normal fact", 0.7), "")


class TestExportBelief(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.belief_path = os.path.join(self.tmpdir, "test.belief")
        self.tree = {
            "version": 1,
            "created": "2026-01-01 00:00:00 UTC",
            "last_updated": "2026-01-01 00:00:00 UTC",
            "root_hash": "",
            "instance": "test",
            "branches": {},
        }

    def _add_leaf(self, branch: str, content: str, confidence: float = 0.7):
        kt.add_knowledge(self.tree, branch, content, source="test", confidence=confidence)

    def test_roundtrip_preserves_branch_and_confidence(self):
        self._add_leaf("technical", "REST endpoints use plural nouns", 0.85)
        self._add_leaf("lessons", "Always validate user input thoroughly", 0.9)

        kt.export_belief(self.tree, self.belief_path, agent_name="test-agent")
        reimported = kt.load_belief(self.belief_path)

        self.assertIn("technical", reimported["branches"])
        self.assertIn("lessons", reimported["branches"])

        tech_leaves = reimported["branches"]["technical"]["leaves"]
        self.assertEqual(len(tech_leaves), 1)
        self.assertAlmostEqual(tech_leaves[0]["confidence"], 0.85)

        lesson_leaves = reimported["branches"]["lessons"]["leaves"]
        self.assertEqual(len(lesson_leaves), 1)
        self.assertAlmostEqual(lesson_leaves[0]["confidence"], 0.9)

    def test_header_format(self):
        self._add_leaf("technical", "Something about REST APIs and design", 0.7)
        kt.export_belief(self.tree, self.belief_path, agent_name="opus")

        with open(self.belief_path) as f:
            header = f.readline().strip()

        parts = header.split("|")
        self.assertEqual(parts[0], "BELIEF")
        self.assertEqual(parts[1], "opus")
        self.assertEqual(parts[3], "v1")

    def test_zettel_line_format(self):
        self._add_leaf("technical", "REST endpoints should use plural nouns", 0.85)
        kt.export_belief(self.tree, self.belief_path)

        with open(self.belief_path) as f:
            lines = f.read().splitlines()

        # Second line should be Z1:...
        z_line = lines[1]
        self.assertTrue(z_line.startswith("Z1:technical|"))
        self.assertIn("|0.85|", z_line)

    def test_content_truncated_to_80(self):
        long_content = "A" * 200
        self._add_leaf("technical", long_content, 0.7)
        kt.export_belief(self.tree, self.belief_path)

        with open(self.belief_path) as f:
            lines = f.read().splitlines()

        z_line = lines[1]
        # Content between quotes should be <= 80 chars
        import re
        m = re.search(r'"([^"]*)"', z_line)
        self.assertIsNotNone(m)
        self.assertLessEqual(len(m.group(1)), 80)

    def test_core_flag_in_export(self):
        self._add_leaf("technical", "Very confident fact here", 0.95)
        kt.export_belief(self.tree, self.belief_path)

        with open(self.belief_path) as f:
            content = f.read()
        self.assertIn("CORE", content)

    def test_counter_flag_in_export(self):
        self._add_leaf("technical", "COUNTER: actually this is wrong", 0.5)
        kt.export_belief(self.tree, self.belief_path)

        with open(self.belief_path) as f:
            content = f.read()
        self.assertIn("COUNTER", content)

    def test_empty_tree_export(self):
        kt.export_belief(self.tree, self.belief_path)
        with open(self.belief_path) as f:
            lines = f.read().splitlines()
        # Just the header
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("BELIEF|"))

    def test_load_belief_rejects_bad_header(self):
        with open(self.belief_path, "w") as f:
            f.write("NOT_A_BELIEF_FILE\n")
        with self.assertRaises(ValueError):
            kt.load_belief(self.belief_path)

    def test_load_belief_rejects_empty_file(self):
        with open(self.belief_path, "w") as f:
            f.write("")
        with self.assertRaises(ValueError):
            kt.load_belief(self.belief_path)

    def test_multiple_branches_sorted(self):
        self._add_leaf("zebra", "Zebra branch content here for testing", 0.7)
        self._add_leaf("alpha", "Alpha branch content here for testing", 0.7)
        kt.export_belief(self.tree, self.belief_path)

        with open(self.belief_path) as f:
            lines = f.read().splitlines()

        # Branches are sorted, so alpha comes before zebra
        self.assertIn("alpha", lines[1])
        self.assertIn("zebra", lines[2])

    def test_reimported_tree_has_valid_hashes(self):
        self._add_leaf("technical", "Hash integrity must be preserved after import", 0.8)
        kt.export_belief(self.tree, self.belief_path)
        reimported = kt.load_belief(self.belief_path)

        ok, errors = kt.verify_tree_integrity(reimported)
        self.assertTrue(ok, f"Integrity errors: {errors}")


if __name__ == "__main__":
    unittest.main()
