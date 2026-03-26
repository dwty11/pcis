#!/usr/bin/env python3
"""Tests for core/belief_decay.py — time-based confidence decay."""

import json
import os
import shutil
import sys
import tempfile

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(TESTS_DIR, "..")
sys.path.insert(0, ROOT_DIR)

from datetime import datetime, timezone, timedelta
from core.belief_decay import decay_confidence, apply_decay_to_tree, EXEMPT_BRANCHES
from core.knowledge_tree import hash_leaf, compute_branch_hash, compute_root_hash


def _make_leaf(content, branch, age_days, confidence=0.9):
    """Create a leaf that was created `age_days` ago."""
    now = datetime.now(timezone.utc)
    created = now - timedelta(days=age_days)
    ts = created.strftime("%Y-%m-%d %H:%M:%S UTC")
    return {
        "id": f"test-{abs(hash(content)) % 10**8}",
        "hash": hash_leaf(content, branch, ts),
        "content": content,
        "source": "test",
        "confidence": confidence,
        "created": ts,
        "promoted_to": None,
    }


class TestDecayMath:
    """Exponential decay formula is correct."""

    def test_zero_age_no_decay(self):
        leaf = _make_leaf("fresh belief", "lessons", age_days=0)
        decayed, age = decay_confidence(leaf, half_life_days=180)
        assert decayed == leaf["confidence"]

    def test_one_half_life_halves_confidence(self):
        leaf = _make_leaf("aging belief", "lessons", age_days=180, confidence=1.0)
        now = datetime.now(timezone.utc)
        decayed, age = decay_confidence(leaf, half_life_days=180, now=now)
        assert abs(decayed - 0.5) < 0.01

    def test_two_half_lives_quarters_confidence(self):
        leaf = _make_leaf("old belief", "lessons", age_days=360, confidence=1.0)
        now = datetime.now(timezone.utc)
        decayed, age = decay_confidence(leaf, half_life_days=180, now=now)
        assert abs(decayed - 0.25) < 0.01

    def test_short_half_life_decays_faster(self):
        leaf = _make_leaf("belief", "lessons", age_days=90, confidence=1.0)
        now = datetime.now(timezone.utc)
        slow, _ = decay_confidence(leaf, half_life_days=180, now=now)
        fast, _ = decay_confidence(leaf, half_life_days=90, now=now)
        assert fast < slow

    def test_confidence_stays_non_negative(self):
        leaf = _make_leaf("ancient belief", "lessons", age_days=3600, confidence=0.5)
        now = datetime.now(timezone.utc)
        decayed, _ = decay_confidence(leaf, half_life_days=180, now=now)
        assert decayed >= 0.0


class TestExemptBranches:
    """Constraints and state branches are never decayed."""

    def _make_tree(self, tmp_dir):
        now = datetime.now(timezone.utc)
        old_ts = (now - timedelta(days=365)).strftime("%Y-%m-%d %H:%M:%S UTC")
        tree = {
            "version": 1,
            "instance": "test",
            "root_hash": "",
            "last_updated": "",
            "branches": {},
        }
        for branch in ["lessons", "constraints", "state"]:
            content = f"{branch} leaf"
            h = hash_leaf(content, branch, old_ts)
            tree["branches"][branch] = {
                "hash": "",
                "leaves": [{
                    "id": f"leaf-{branch}",
                    "hash": h,
                    "content": content,
                    "source": "test",
                    "confidence": 0.9,
                    "created": old_ts,
                    "promoted_to": None,
                }],
            }
        for bname in tree["branches"]:
            tree["branches"][bname]["hash"] = compute_branch_hash(
                tree["branches"][bname]["leaves"]
            )
        tree["root_hash"] = compute_root_hash(tree)

        tree_path = os.path.join(tmp_dir, "data", "tree.json")
        os.makedirs(os.path.dirname(tree_path), exist_ok=True)
        with open(tree_path, "w") as f:
            json.dump(tree, f)
        return tree_path, tree

    def test_exempt_branches_untouched(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            tree_path, original_tree = self._make_tree(tmp_dir)
            constraints_conf = original_tree["branches"]["constraints"]["leaves"][0]["confidence"]
            state_conf = original_tree["branches"]["state"]["leaves"][0]["confidence"]

            summary = apply_decay_to_tree(tree_path, half_life_days=180, dry_run=True)

            # Reload to check — dry_run shouldn't write, but decay_confidence was applied in memory
            # The summary should show skipped for exempt branches
            assert summary["skipped"] == 2  # constraints + state
            assert summary["updated"] == 1  # only lessons

            # Verify the file wasn't written (dry_run)
            with open(tree_path) as f:
                tree_after = json.load(f)
            assert tree_after["branches"]["constraints"]["leaves"][0]["confidence"] == constraints_conf
            assert tree_after["branches"]["state"]["leaves"][0]["confidence"] == state_conf
        finally:
            shutil.rmtree(tmp_dir)

    def test_exempt_set_contents(self):
        assert "constraints" in EXEMPT_BRANCHES
        assert "state" in EXEMPT_BRANCHES
        assert "lessons" not in EXEMPT_BRANCHES


class TestDryRun:
    """Dry run computes decay but does not write to disk."""

    def test_dry_run_no_file_write(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            now = datetime.now(timezone.utc)
            old_ts = (now - timedelta(days=365)).strftime("%Y-%m-%d %H:%M:%S UTC")
            tree = {
                "version": 1,
                "instance": "test",
                "root_hash": "",
                "last_updated": "",
                "branches": {
                    "lessons": {
                        "hash": "",
                        "leaves": [{
                            "id": "leaf-1",
                            "hash": hash_leaf("old belief", "lessons", old_ts),
                            "content": "old belief",
                            "source": "test",
                            "confidence": 0.9,
                            "created": old_ts,
                            "promoted_to": None,
                        }],
                    }
                },
            }
            for bname in tree["branches"]:
                tree["branches"][bname]["hash"] = compute_branch_hash(
                    tree["branches"][bname]["leaves"]
                )
            tree["root_hash"] = compute_root_hash(tree)

            tree_path = os.path.join(tmp_dir, "data", "tree.json")
            os.makedirs(os.path.dirname(tree_path), exist_ok=True)
            with open(tree_path, "w") as f:
                json.dump(tree, f)

            mtime_before = os.path.getmtime(tree_path)

            summary = apply_decay_to_tree(tree_path, dry_run=True)
            assert summary["updated"] == 1

            mtime_after = os.path.getmtime(tree_path)
            assert mtime_before == mtime_after, "dry_run wrote to disk"

            # Confidence on disk unchanged
            with open(tree_path) as f:
                on_disk = json.load(f)
            assert on_disk["branches"]["lessons"]["leaves"][0]["confidence"] == 0.9
        finally:
            shutil.rmtree(tmp_dir)

    def test_wet_run_writes(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            now = datetime.now(timezone.utc)
            old_ts = (now - timedelta(days=365)).strftime("%Y-%m-%d %H:%M:%S UTC")
            tree = {
                "version": 1,
                "instance": "test",
                "root_hash": "",
                "last_updated": "",
                "branches": {
                    "lessons": {
                        "hash": "",
                        "leaves": [{
                            "id": "leaf-1",
                            "hash": hash_leaf("old belief", "lessons", old_ts),
                            "content": "old belief",
                            "source": "test",
                            "confidence": 0.9,
                            "created": old_ts,
                            "promoted_to": None,
                        }],
                    }
                },
            }
            for bname in tree["branches"]:
                tree["branches"][bname]["hash"] = compute_branch_hash(
                    tree["branches"][bname]["leaves"]
                )
            tree["root_hash"] = compute_root_hash(tree)

            tree_path = os.path.join(tmp_dir, "data", "tree.json")
            os.makedirs(os.path.dirname(tree_path), exist_ok=True)
            with open(tree_path, "w") as f:
                json.dump(tree, f)

            summary = apply_decay_to_tree(tree_path, dry_run=False)
            assert summary["updated"] == 1

            with open(tree_path) as f:
                on_disk = json.load(f)
            new_conf = on_disk["branches"]["lessons"]["leaves"][0]["confidence"]
            assert new_conf < 0.9, f"Expected decayed confidence < 0.9, got {new_conf}"

            # Hashes should be recomputed (save_tree calls _write_tree)
            assert on_disk["root_hash"] != ""
        finally:
            shutil.rmtree(tmp_dir)
