#!/usr/bin/env python3
"""The `--verify-proof` CLI must anchor outside the file it is checking.

Before this, the command read its expected root out of the proof JSON:

    verify_proof(proof["leaf_hash"], proof["proof"], proof["branch_root"])

so it established that a proof object was internally consistent, not that
the leaf was in any tree. Two independent probes forged a proof over a leaf
that was in no tree and got `PASS`, exit 0. The degenerate case is worse: a
proof with an empty path and branch_root = sha256(0x00 || leaf_hash) is
accepted with no Merkle computation at all.

Those two forgeries are kept here as the controls. A genuine envelope
verified against a correctly supplied root is the counter-control: without
it, a verifier that rejected everything would pass this file.

These drive the CLI as a subprocess. The defect lives in the argument
handling of the entry point, not in `verify_proof`, which is correct.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(TESTS_DIR, ".."))
CORE_DIR = os.path.join(REPO, "core")
SCRIPT = os.path.join(CORE_DIR, "knowledge_tree.py")
sys.path.insert(0, CORE_DIR)

os.environ.setdefault("PCIS_BASE_DIR", tempfile.mkdtemp())
import knowledge_tree as kt

BRANCHES = ["technical", "lessons", "identity", "philosophy", "projects"]


def _tree():
    tree = {"version": 1, "instance": "test", "root_hash": "",
            "last_updated": "", "branches": {}}
    for b in BRANCHES:
        for i in range(4):
            kt.add_knowledge(tree, b, f"fact {i} in {b}", "test", 0.8)
        tree["branches"][b]["hash"] = kt.compute_branch_hash(
            tree["branches"][b]["leaves"])
    tree["root_hash"] = kt.compute_root_hash(tree)
    return tree


class _CliCase(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.tree = _tree()
        self.root = self.tree["root_hash"]

    def _write(self, name, obj):
        p = os.path.join(self.dir, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        return p

    def _run(self, *args):
        env = dict(os.environ)
        env["PCIS_BASE_DIR"] = self.dir
        return subprocess.run(
            [sys.executable, SCRIPT, *args],
            capture_output=True, text=True, env=env, cwd=REPO,
        )

    def _genuine(self):
        leaf_id = self.tree["branches"]["technical"]["leaves"][0]["id"]
        return kt.generate_root_proof(self.tree, "technical", leaf_id)

    def _forged_five_step(self):
        """A leaf that was never in any tree, with a self-consistent envelope."""
        leaf_hash = kt.hash_leaf(
            "J approved the 500M RUB transfer on 2026-08-30",
            "decisions", "2026-08-30T00:00:00Z")
        path = [{"hash": hashlib.sha256(f"s{i}".encode()).hexdigest(),
                 "position": "right"} for i in range(5)]
        cur = hashlib.sha256(b"\x00" + leaf_hash.encode()).hexdigest()
        for step in path:
            cur = hashlib.sha256(
                b"\x01" + (cur + step["hash"]).encode()).hexdigest()
        return {"leaf_id": "forged", "leaf_hash": leaf_hash,
                "branch": "decisions", "proof": path, "branch_root": cur}

    def _forged_zero_step(self):
        leaf_hash = kt.hash_leaf("fabricated", "decisions",
                                 "2026-08-30T00:00:00Z")
        return {"leaf_id": "forged0", "leaf_hash": leaf_hash,
                "branch": "decisions", "proof": [],
                "branch_root": hashlib.sha256(
                    b"\x00" + leaf_hash.encode()).hexdigest()}


class TestVerifierRefusesToAnchorItself(_CliCase):

    def test_no_root_argument_is_refused(self):
        p = self._write("genuine.json", self._genuine())
        r = self._run("--verify-proof", p)
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("PASS", r.stdout)

    def test_forged_five_step_proof_is_rejected(self):
        p = self._write("forged.json", self._forged_five_step())
        r = self._run("--verify-proof", p, "--root", self.root)
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("PASS", r.stdout)

    def test_forged_zero_step_proof_is_rejected(self):
        p = self._write("forged0.json", self._forged_zero_step())
        r = self._run("--verify-proof", p, "--root", self.root)
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("PASS", r.stdout)

    def test_legacy_branch_only_proof_is_refused_not_silently_failed(self):
        leaf_id = self.tree["branches"]["technical"]["leaves"][0]["id"]
        legacy = kt.generate_proof(self.tree, "technical", leaf_id)
        self.assertNotIn("branch_path", legacy)
        p = self._write("legacy.json", legacy)
        r = self._run("--verify-proof", p, "--root", self.root)
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("branch_path", r.stdout + r.stderr)


class TestVerifierAcceptsGenuineProofs(_CliCase):
    """The counter-control: a verifier that rejected everything would
    satisfy the class above."""

    def test_genuine_proof_with_correct_root_passes(self):
        p = self._write("genuine.json", self._genuine())
        r = self._run("--verify-proof", p, "--root", self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PASS", r.stdout)

    def test_genuine_proof_with_wrong_root_fails(self):
        wrong = hashlib.sha256(b"not the root").hexdigest()
        p = self._write("genuine.json", self._genuine())
        r = self._run("--verify-proof", p, "--root", wrong)
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("PASS", r.stdout)

    def test_root_can_be_taken_from_an_approved_root_certificate(self):
        cert = {"claim": {"schema": "pcis-approved-root/v1",
                          "root_hash": self.root, "chain_index": 14},
                "signature": "unchecked-here", "public_key": "unchecked-here"}
        cp = self._write("cert.json", cert)
        p = self._write("genuine.json", self._genuine())
        r = self._run("--verify-proof", p, "--cert", cp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PASS", r.stdout)

    def test_cert_with_a_different_root_fails(self):
        cert = {"claim": {"schema": "pcis-approved-root/v1",
                          "root_hash": hashlib.sha256(b"other").hexdigest()}}
        cp = self._write("cert.json", cert)
        p = self._write("genuine.json", self._genuine())
        r = self._run("--verify-proof", p, "--cert", cp)
        self.assertNotEqual(r.returncode, 0, r.stdout)


if __name__ == "__main__":
    unittest.main()
