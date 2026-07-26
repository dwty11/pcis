"""test_validator_merkle_symmetry.py — before/after must be measured the same way.

Producer 2 of the merkle_root_before/after pair. Found by grepping the VALUE
rather than the caption (the file contains no caption at all), then fixed at
one end only — the grep worked, the follow-through did not.

``merkle_before`` was ``compute_root_hash(tree)`` over the tree's STORED branch
hashes, while ``merkle_after`` recomputed every branch hash from leaf content
first. With a stale stored branch hash and no content change whatsoever, the
two differ — and the output lands in adversarial_validation_run.json, served by
/api/external-validation as the fallback into the MERKLE ROOT TRANSITION block.
A difference in derivation method, captioned as change over time.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, _ROOT)


def _tree_with_stale_branch_hash():
    import knowledge_tree as kt

    tree = {"branches": {}, "root_hash": ""}
    kt.add_knowledge(tree, "technical", "a claim", source="t", confidence=0.8)
    kt.add_knowledge(tree, "lessons", "another claim", source="t", confidence=0.8)
    # A stale STORED branch hash, with content untouched. This is ordinary —
    # any writer that forgets to rehash a branch leaves the tree in this state.
    tree["branches"]["technical"]["hash"] = "s" * 64
    return tree


def test_stale_branch_hash_alone_does_not_manufacture_a_transition():
    """No content changed, so before and after must agree."""
    from core.adversarial_validator import _merkle_snapshot

    tree = _tree_with_stale_branch_hash()

    before = _merkle_snapshot(tree)
    after = _merkle_snapshot(tree)

    assert before == after, (
        "with identical content, a stale stored branch hash must not make the "
        "two ends of a before/after pair disagree"
    )


def test_snapshot_is_derived_from_content_not_stored_hashes():
    from core.adversarial_validator import _merkle_snapshot
    from knowledge_tree import compute_branch_hash, compute_root_hash

    tree = _tree_with_stale_branch_hash()

    expected = json.loads(json.dumps(tree))
    for name, branch in expected["branches"].items():
        branch["hash"] = compute_branch_hash(branch["leaves"])

    assert _merkle_snapshot(tree) == compute_root_hash(expected)
    assert _merkle_snapshot(tree) != compute_root_hash(tree), (
        "fixture assumption: the stored-hash route gives a different answer"
    )


def test_a_real_content_change_still_moves_it():
    """Symmetry must not be bought by making the value insensitive."""
    import knowledge_tree as kt
    from core.adversarial_validator import _merkle_snapshot

    tree = _tree_with_stale_branch_hash()
    before = _merkle_snapshot(tree)

    kt.add_knowledge(tree, "lessons", "a genuinely new claim")
    after = _merkle_snapshot(tree)

    assert before != after


def test_snapshot_does_not_mutate_the_caller_tree():
    """The validator is documented read-only over demo_tree.json."""
    from core.adversarial_validator import _merkle_snapshot

    tree = _tree_with_stale_branch_hash()
    frozen = json.dumps(tree, sort_keys=True)

    _merkle_snapshot(tree)

    assert json.dumps(tree, sort_keys=True) == frozen, (
        "computing a snapshot must not rewrite the tree it was handed"
    )
