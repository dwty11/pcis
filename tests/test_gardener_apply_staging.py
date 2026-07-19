#!/usr/bin/env python3
"""`gardener.py --apply-staging` must honor `--dry-run`.

Bug (P0-5a): `--apply-staging --dry-run` committed staged items and cleared the
staging file despite --dry-run — main() never passed the flag through, and
apply_staging() had no dry-run mode. Following the documented session-start
"check staged challenges" protocol therefore silently committed unreviewed
challenges. These guard the fix.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "core"))
# gardener.py hard-exits at import if PCIS_BASE_DIR is unset — set a throwaway.
os.environ.setdefault("PCIS_BASE_DIR", tempfile.mkdtemp())

import gardener  # noqa: E402


def _write_staging(tmp_path):
    staging = tmp_path / "gardener-staging.md"
    staging.write_text(
        json.dumps({"type": "counter", "branch": "lessons",
                    "content": "COUNTER: [abc123] a staged test challenge",
                    "confidence": 0.6}) + "\n"
        + json.dumps({"type": "gap", "branch": "lessons",
                      "content": "a staged knowledge gap", "confidence": 0.8}) + "\n"
    )
    return staging


def test_apply_staging_dry_run_leaves_staging_and_tree_untouched(monkeypatch, tmp_path):
    staging = _write_staging(tmp_path)
    monkeypatch.setattr(gardener, "GARDEN_STAGING", str(staging))
    # A dry run must never open the tree for writing.
    monkeypatch.setattr(gardener, "tree_lock",
                        lambda *a, **k: pytest.fail("tree_lock opened during --dry-run (would mutate the tree)"))

    n = gardener.apply_staging(dry_run=True)

    assert n == 2, "dry-run should report the 2 staged items that would be applied"
    assert staging.exists(), "dry-run must NOT delete the staging file"
    assert staging.read_text().strip(), "staging file contents must be left intact"


def test_main_apply_staging_passes_dry_run(monkeypatch):
    captured = {}

    def _fake_apply(dry_run=False):
        captured["dry_run"] = dry_run
        return 0

    monkeypatch.setattr(gardener, "apply_staging", _fake_apply)
    monkeypatch.setattr(sys, "argv", ["gardener.py", "--apply-staging", "--dry-run"])

    gardener.main()

    assert captured.get("dry_run") is True, "main() must pass --dry-run through to apply_staging"
