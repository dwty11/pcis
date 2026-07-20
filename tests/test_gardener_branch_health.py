#!/usr/bin/env python3
"""2.6 — the adversarial gardener prompt must feed MEASURED branch health, not a
hardcoded "every branch is an echo chamber" assertion.

Priming the adversarial pass with an unmeasured premise about the very tree it is
attacking is a real bug in a system whose pitch is self-challenge. The prompt
should show measured per-branch stats and let the model judge.
"""
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "core"))
os.environ.setdefault("PCIS_BASE_DIR", tempfile.mkdtemp())

import gardener  # noqa: E402


def _tree():
    return {"branches": {
        "identity": {"leaves": [
            {"content": "a", "confidence": 0.90},
            {"content": "b", "confidence": 0.92},
        ]},
        "lessons": {"leaves": [
            {"content": "c", "confidence": 0.40},
            {"content": "d", "confidence": 0.80},
        ]},
    }}


def test_compute_branch_health_reports_measured_mean_and_spread():
    out = gardener.compute_branch_health(_tree())
    # identity: mean 0.91, spread 0.02  -> tight+high (echo-chamber signature)
    assert "identity" in out and "0.91" in out and "0.02" in out, out
    # lessons: mean 0.60, spread 0.40  -> diverse
    assert "lessons" in out and "0.60" in out and "0.40" in out, out


def test_prompt_feeds_measured_health_not_hardcoded_assertion():
    # the false blanket premise is gone
    assert "Every branch has high confidence and low spread" not in gardener.GARDENER_PROMPT
    # the template pulls in measured branch health
    assert "{branch_health}" in gardener.GARDENER_PROMPT
    # formatting with all documented keys succeeds (the wiring contract)
    filled = gardener.GARDENER_PROMPT.format(
        tree_text="T", recent_memory="M", already_challenged="A",
        branch_list="identity, lessons",
        branch_health="- identity: 2 leaves, mean confidence 0.91, spread 0.02",
    )
    assert "mean confidence 0.91" in filled
