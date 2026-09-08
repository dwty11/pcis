#!/usr/bin/env python3
"""Leaf-to-signed-root inclusion proofs.

`generate_proof` reaches a branch root. The value `sign_root` signs is the
TREE root, built by `compute_root_hash` as a second Merkle construction over
`f"{name}:{branch_hash}"` preimages. Until the branch-to-root sibling path is
emitted, a proof holder cannot verify inclusion under the signed root — the
gap this module's tests pin shut.

The three cases named in the ruling that authorised this work:
  - a real leaf verifies to the live root
  - a leaf from a different tree does not
  - a proof with a tampered sibling fails

The second and third are the controls: without them the first is a green
light for nothing, because a verifier that returns True unconditionally
would satisfy it.
"""

import os
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_DIR = os.path.join(TESTS_DIR, "..", "core")
sys.path.insert(0, CORE_DIR)

os.environ.setdefault("PCIS_BASE_DIR", tempfile.mkdtemp())
import knowledge_tree as kt

BRANCHES = ["technical", "lessons", "identity", "philosophy", "projects"]


def _tree(seed="a", branches=BRANCHES, per_branch=4):
    """A real tree, built through add_knowledge, with its hashes settled.

    Multiple branches on purpose: with one branch the top construction has a
    single level and the branch-to-root path is empty, which would let a
    broken implementation pass.
    """
    tree = {"version": 1, "instance": "test", "root_hash": "",
            "last_updated": "", "branches": {}}
    for b in branches:
        for i in range(per_branch):
            kt.add_knowledge(tree, b, f"{seed} fact {i} in {b}", "test", 0.8)
        tree["branches"][b]["hash"] = kt.compute_branch_hash(
            tree["branches"][b]["leaves"])
    tree["root_hash"] = kt.compute_root_hash(tree)
    return tree


def _first_leaf(tree, branch):
    return tree["branches"][branch]["leaves"][0]["id"]


class TestBranchToRootPath(unittest.TestCase):

    def test_branch_path_folds_to_the_tree_root_for_every_branch(self):
        tree = _tree()
        for branch in BRANCHES:
            bp = kt.generate_branch_path(tree, branch)
            preimage = f"{branch}:{tree['branches'][branch]['hash']}"
            self.assertTrue(
                kt.verify_proof(preimage, bp["path"], tree["root_hash"]),
                f"branch path for {branch} did not reconstruct the tree root",
            )

    def test_branch_path_is_siblings_not_the_whole_tree(self):
        """The point of the exercise: the hop is small."""
        tree = _tree()
        bp = kt.generate_branch_path(tree, "technical")
        # 5 branches -> levels [5,3,2,1] -> 3 siblings
        self.assertEqual(len(bp["path"]), 3)
        for step in bp["path"]:
            self.assertIn(step["position"], ("left", "right"))
            self.assertEqual(len(step["hash"]), 64)


class TestLeafToSignedRoot(unittest.TestCase):

    def test_a_real_leaf_verifies_to_the_live_root(self):
        tree = _tree()
        env = kt.generate_root_proof(tree, "technical", _first_leaf(tree, "technical"))
        self.assertTrue(kt.verify_root_proof(env, tree["root_hash"]))

    def test_every_leaf_in_every_branch_verifies_to_the_live_root(self):
        tree = _tree()
        for branch in BRANCHES:
            for leaf in tree["branches"][branch]["leaves"]:
                env = kt.generate_root_proof(tree, branch, leaf["id"])
                self.assertTrue(
                    kt.verify_root_proof(env, tree["root_hash"]),
                    f"leaf {leaf['id']} in {branch} failed to reach the root",
                )

    def test_a_leaf_from_a_different_tree_does_not_verify(self):
        tree_a = _tree(seed="a")
        tree_b = _tree(seed="b")
        self.assertNotEqual(tree_a["root_hash"], tree_b["root_hash"])
        env_b = kt.generate_root_proof(tree_b, "technical", _first_leaf(tree_b, "technical"))
        # The envelope is internally valid against its OWN root — the control
        # that proves this assertion can pass.
        self.assertTrue(kt.verify_root_proof(env_b, tree_b["root_hash"]))
        # ...and must not verify against a different tree's root.
        self.assertFalse(kt.verify_root_proof(env_b, tree_a["root_hash"]))

    def test_a_tampered_branch_path_sibling_fails(self):
        tree = _tree()
        env = kt.generate_root_proof(tree, "technical", _first_leaf(tree, "technical"))
        self.assertTrue(kt.verify_root_proof(env, tree["root_hash"]))
        h = env["branch_path"][0]["hash"]
        env["branch_path"][0]["hash"] = ("0" if h[0] != "0" else "1") + h[1:]
        self.assertFalse(kt.verify_root_proof(env, tree["root_hash"]))

    def test_a_tampered_leaf_leg_sibling_fails(self):
        tree = _tree()
        env = kt.generate_root_proof(tree, "technical", _first_leaf(tree, "technical"))
        h = env["proof"][0]["hash"]
        env["proof"][0]["hash"] = ("0" if h[0] != "0" else "1") + h[1:]
        self.assertFalse(kt.verify_root_proof(env, tree["root_hash"]))

    def test_a_forged_leaf_hash_does_not_verify(self):
        tree = _tree()
        env = kt.generate_root_proof(tree, "technical", _first_leaf(tree, "technical"))
        env["leaf_hash"] = kt.hash_leaf("fabricated", "technical", "2026-09-01T00:00:00Z")
        self.assertFalse(kt.verify_root_proof(env, tree["root_hash"]))

    def test_envelope_carries_the_root_it_claims(self):
        """The envelope must name a root, so a verifier can be anchored outside it."""
        tree = _tree()
        env = kt.generate_root_proof(tree, "technical", _first_leaf(tree, "technical"))
        self.assertEqual(env["root_hash"], tree["root_hash"])
        self.assertEqual(env["branch_root"], tree["branches"]["technical"]["hash"])


if __name__ == "__main__":
    unittest.main()
