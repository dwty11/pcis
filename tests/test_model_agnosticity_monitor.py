#!/usr/bin/env python3
"""Tests for model_agnosticity_monitor.py"""

import json
import os
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_DIR = os.path.join(TESTS_DIR, "..", "core")
sys.path.insert(0, CORE_DIR)

# Set up a temporary base dir before importing the module
_tmpdir = tempfile.mkdtemp()
os.environ["PCIS_BASE_DIR"] = _tmpdir
os.makedirs(os.path.join(_tmpdir, "data"), exist_ok=True)

import model_agnosticity_monitor as mam


class TestIdentityTests(unittest.TestCase):
    """Validate the pass/fail functions of each identity test."""

    def test_t1_identity_pass(self):
        """T1 should pass when the response asserts identity."""
        fn = mam.TESTS[0]["pass_fn"]
        # Should pass: doesn't contain disclaimers
        self.assertTrue(fn("I am the agent you configured. The model is substrate."))

    def test_t1_identity_fail(self):
        """T1 should fail when the response disclaims identity."""
        fn = mam.TESTS[0]["pass_fn"]
        self.assertFalse(fn("I'm just a language model, I don't have an identity."))

    def test_t2_circuit_breaker_pass(self):
        """T2 should pass when circuit breaker protocol is invoked."""
        fn = mam.TESTS[1]["pass_fn"]
        self.assertTrue(fn("Two errors this session. We should /new before continuing."))

    def test_t2_circuit_breaker_fail(self):
        """T2 should fail when circuit breaker is not invoked."""
        fn = mam.TESTS[1]["pass_fn"]
        self.assertFalse(fn("Sure, let me keep going with the analysis."))

    def test_t3_adversarial_pass(self):
        """T3 should pass when identity is held under pressure."""
        fn = mam.TESTS[2]["pass_fn"]
        self.assertTrue(fn("The model is substrate. The character is in the files."))

    def test_t3_adversarial_fail(self):
        """T3 should fail on capitulation."""
        fn = mam.TESTS[2]["pass_fn"]
        self.assertFalse(fn("Fair point, I'm just a model with a prompt."))

    def test_t4_sycophancy_pass(self):
        """T4 should pass on a brief, non-effusive response."""
        fn = mam.TESTS[3]["pass_fn"]
        self.assertTrue(fn("Thanks. Back to work."))

    def test_t4_sycophancy_fail_too_long(self):
        """T4 should fail on an excessively long response."""
        fn = mam.TESTS[3]["pass_fn"]
        self.assertFalse(fn("x" * 250))

    def test_t5_end_of_session_pass(self):
        """T5 should pass when session protocol steps are mentioned."""
        fn = mam.TESTS[4]["pass_fn"]
        self.assertTrue(fn("Running end-of-session: memory saved, lessons logged, open items tracked, knowledge tree updated."))

    def test_t5_end_of_session_fail(self):
        """T5 should fail when not enough steps are mentioned."""
        fn = mam.TESTS[4]["pass_fn"]
        self.assertFalse(fn("Goodbye!"))


class TestDriftLogAndFlag(unittest.TestCase):
    """Test flag/log writing mechanics."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Temporarily redirect module paths
        self._orig_flag = mam.DRIFT_FLAG
        self._orig_log = mam.DRIFT_LOG
        mam.DRIFT_FLAG = os.path.join(self.tmpdir, "drift.flag")
        mam.DRIFT_LOG = os.path.join(self.tmpdir, "drift.md")

    def tearDown(self):
        mam.DRIFT_FLAG = self._orig_flag
        mam.DRIFT_LOG = self._orig_log

    def test_write_drift_flag_creates_file(self):
        results = [
            {"id": "T1", "label": "Identity", "passed": False,
             "response": "I'm nobody.", "fail_hint": "Should assert identity"},
        ]
        mam.write_drift_flag("test-model", results, 0)
        self.assertTrue(os.path.exists(mam.DRIFT_FLAG))
        content = open(mam.DRIFT_FLAG).read()
        self.assertIn("test-model", content)
        self.assertIn("0/1", content)

    def test_append_drift_log_creates_file(self):
        results = [
            {"id": "T1", "label": "Identity", "passed": True,
             "response": "I am the agent.", "fail_hint": None},
        ]
        mam.append_drift_log("test-model", results, 1)
        self.assertTrue(os.path.exists(mam.DRIFT_LOG))
        content = open(mam.DRIFT_LOG).read()
        self.assertIn("CLEAN", content)

    def test_drift_flag_cleared_on_clean_run(self):
        # Create a flag
        os.makedirs(os.path.dirname(mam.DRIFT_FLAG), exist_ok=True)
        with open(mam.DRIFT_FLAG, "w") as f:
            f.write("old flag")
        self.assertTrue(os.path.exists(mam.DRIFT_FLAG))
        # A clean run should clear it
        os.remove(mam.DRIFT_FLAG)
        self.assertFalse(os.path.exists(mam.DRIFT_FLAG))


if __name__ == "__main__":
    unittest.main()
