#!/usr/bin/env python3
"""Every UTC timestamp helper must always carry 6-digit microseconds.

A bare ``datetime.now(timezone.utc).isoformat()`` omits the fractional part
whenever ``microsecond`` is exactly 0 — about one call in a million. The
resulting stamp sorts as *less than* every microsecond-bearing stamp inside
the same second, so an append-only log ordered by timestamp string silently
collapses distinct events into a tie at precisely the moment ordering
matters. That is the sort-tie collapse the UTC/microsecond ruling exists to
prevent.

``core/retrieval_trace.py:339`` already pins this with
``timespec="microseconds"`` and a test. This module holds the rest of the
codebase to the same contract.

Scope note: the carry-forward named only ``core/events.py``. The defect is
shared by all three ``_now_iso_utc`` helpers and by ``core/signing.py``'s
inline ``signed_at``. ``events`` and ``action_log`` are the load-bearing
cases (append-only, ordered); ``audit`` and ``signing`` write single records
where a tie cannot bite, but they are the same one-token defect and are
pinned here so the class cannot regress piecemeal.
"""

import importlib
import os
import re
import sys
from datetime import datetime, timezone

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, _ROOT)

# The exact edge a bare .isoformat() loses.
_ZERO_US = datetime(2026, 7, 25, 12, 0, 0, 0, tzinfo=timezone.utc)
_EXPECTED = "2026-07-25T12:00:00.000000+00:00"

# Every module exposing a _now_iso_utc() helper.
HELPER_MODULES = ["events", "audit", "action_log"]


class _FixedDatetime(datetime):
    """datetime whose now() lands exactly on a zero-microsecond instant."""

    @classmethod
    def now(cls, tz=None):
        return _ZERO_US


@pytest.mark.parametrize("module_name", HELPER_MODULES)
def test_now_iso_utc_keeps_microseconds_when_zero(module_name, monkeypatch):
    """The edge case: microsecond == 0 must still render as .000000."""
    module = importlib.import_module(module_name)
    monkeypatch.setattr(module, "datetime", _FixedDatetime)

    ts = module._now_iso_utc()

    assert ts == _EXPECTED, (
        f"{module_name}._now_iso_utc() dropped the fractional part: {ts!r}"
    )


@pytest.mark.parametrize("module_name", HELPER_MODULES)
def test_now_iso_utc_shape_on_the_real_clock(module_name):
    """UTC, +00:00 form, 6-digit microseconds — against the real clock."""
    module = importlib.import_module(module_name)

    ts = module._now_iso_utc()

    assert datetime.fromisoformat(ts).utcoffset().total_seconds() == 0, (
        f"{module_name}: not UTC: {ts!r}"
    )
    assert re.search(r"\.\d{6}\+00:00$", ts), (
        f"{module_name}: expected 6-digit microseconds, got {ts!r}"
    )


def test_sorting_is_stable_across_the_zero_microsecond_boundary():
    """Why this matters: the truncated form sorts before its own second.

    This is the failure the helpers would produce, demonstrated on literals
    so it holds regardless of which module is under test.
    """
    truncated = "2026-07-25T12:00:00+00:00"
    later_same_second = "2026-07-25T12:00:00.000001+00:00"
    padded = _EXPECTED

    # Correct: padded sorts before a later stamp in the same second.
    assert padded < later_same_second

    # The defect: string-sorting a truncated stamp against a padded one
    # works here by luck, but the two forms are not comparable as text —
    # '+' (0x2B) sorts below '.' (0x2E), so a truncated stamp always sorts
    # first within its second, even against 12:00:00.000000 itself.
    assert truncated < padded
    assert datetime.fromisoformat(truncated) == datetime.fromisoformat(padded), (
        "same instant, two different sort positions — that is the collapse"
    )


def test_signing_signed_at_keeps_microseconds_when_zero(tmp_path, monkeypatch):
    """core/signing.py's inline signed_at is the same defect.

    Driven through the real ``sign_root`` path, not the helper, because
    signing.py has no ``_now_iso_utc`` to patch.
    """
    pytest.importorskip("nacl", reason="PyNaCl not installed")

    monkeypatch.setenv("PCIS_BASE_DIR", str(tmp_path))
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    import signing
    from knowledge_tree import (
        DEFAULT_BRANCHES,
        add_knowledge,
        compute_branch_hash,
        now_utc,
    )

    tree = {
        "version": 1,
        "created": now_utc(),
        "last_updated": now_utc(),
        "root_hash": "",
        "instance": "timestamp-test",
        "branches": {b: {"hash": "", "leaves": []} for b in DEFAULT_BRANCHES},
    }
    add_knowledge(tree, "technical", "a leaf to sign over", confidence=0.85)
    for bname in tree["branches"]:
        tree["branches"][bname]["hash"] = compute_branch_hash(
            tree["branches"][bname]["leaves"]
        )

    signing.generate_keypair(key_dir=str(data_dir))
    monkeypatch.setattr(signing, "datetime", _FixedDatetime)

    result = signing.sign_root(tree=tree)

    assert result["signed_at"] == _EXPECTED, (
        f"signing.sign_root dropped the fractional part: {result['signed_at']!r}"
    )
