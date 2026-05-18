#!/usr/bin/env python3
"""Tests for gardener_healthcheck.py"""

import os
import sys
import tempfile
import time
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_DIR = os.path.join(TESTS_DIR, "..", "core")
sys.path.insert(0, CORE_DIR)

_tmpdir = tempfile.mkdtemp()
os.environ["PCIS_BASE_DIR"] = _tmpdir
os.makedirs(os.path.join(_tmpdir, "data"), exist_ok=True)

import gardener_healthcheck as ghc


class TestHealthcheck(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_log = ghc.LOG_FILE
        self._orig_flag = ghc.FLAG_FILE
        ghc.LOG_FILE = os.path.join(self.tmpdir, "gardener-last.log")
        ghc.FLAG_FILE = os.path.join(self.tmpdir, "gardener-health.flag")

    def tearDown(self):
        ghc.LOG_FILE = self._orig_log
        ghc.FLAG_FILE = self._orig_flag

    def test_missing_log_file(self):
        """MISSING status when log file does not exist."""
        status, detail = ghc.check()
        self.assertEqual(status, "MISSING")
        self.assertTrue(os.path.exists(ghc.FLAG_FILE))

    def test_ok_status_recent_success(self):
        """OK status when log contains success marker and is recent."""
        with open(ghc.LOG_FILE, "w") as f:
            f.write("Gardener starting\nDoing work...\nGardening complete\n")
        status, detail = ghc.check()
        self.assertEqual(status, "OK")
        self.assertFalse(os.path.exists(ghc.FLAG_FILE))

    def test_error_status(self):
        """ERROR status when log contains error markers."""
        with open(ghc.LOG_FILE, "w") as f:
            f.write("Gardener starting\nERROR: something went wrong\n")
        status, detail = ghc.check()
        self.assertEqual(status, "ERROR")
        self.assertTrue(os.path.exists(ghc.FLAG_FILE))

    def test_unknown_status(self):
        """UNKNOWN status when log has no success or error markers."""
        with open(ghc.LOG_FILE, "w") as f:
            f.write("Gardener starting\nSome output without markers\n")
        status, detail = ghc.check()
        self.assertEqual(status, "UNKNOWN")
        self.assertTrue(os.path.exists(ghc.FLAG_FILE))

    def test_ok_clears_existing_flag(self):
        """OK status removes a pre-existing flag file."""
        # Create flag
        with open(ghc.FLAG_FILE, "w") as f:
            f.write("old flag\n")
        # Write successful log
        with open(ghc.LOG_FILE, "w") as f:
            f.write("Gardener starting\nGardening complete\n")
        status, _ = ghc.check()
        self.assertEqual(status, "OK")
        self.assertFalse(os.path.exists(ghc.FLAG_FILE))

    def test_flag_file_content(self):
        """Flag file should contain status, timestamp, detail, and action."""
        status, detail = ghc.check()  # No log => MISSING
        self.assertTrue(os.path.exists(ghc.FLAG_FILE))
        content = open(ghc.FLAG_FILE).read()
        self.assertIn("GARDENER HEALTH: MISSING", content)
        self.assertIn("Detail:", content)
        self.assertIn("Action:", content)

    def test_stale_log(self):
        """STALE status when log file is older than 24 hours."""
        with open(ghc.LOG_FILE, "w") as f:
            f.write("Gardener starting\nGardening complete\n")
        # Set mtime to 25 hours ago
        old_time = time.time() - 25 * 3600
        os.utime(ghc.LOG_FILE, (old_time, old_time))
        status, detail = ghc.check()
        self.assertEqual(status, "STALE")

    def test_dry_run_success(self):
        """DRY RUN complete marker counts as success."""
        with open(ghc.LOG_FILE, "w") as f:
            f.write("Gardener starting\nDRY RUN complete\n")
        status, _ = ghc.check()
        self.assertEqual(status, "OK")


if __name__ == "__main__":
    unittest.main()
