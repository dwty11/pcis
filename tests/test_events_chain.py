#!/usr/bin/env python3
"""Tests for events.py chain semantics — the contract that gardener.py relies on.

These tests verify the events module API end-to-end without touching gardener
internals. They mirror the gardener's expected flow: emit → (optionally) resolve
→ verify, plus the non-fatal behaviour gardener depends on (missing journal).
"""

import hashlib
import json
import os
import sys

import pytest

# Make core/ importable
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, _ROOT)


def _journal_in(tmp_path):
    """Per-test journal path, fully isolated from any default location."""
    return str(tmp_path / "events.action.jsonl")


# -----------------------------------------------------------------------
# 1. Chain integrity — emit → resolve → verify
# -----------------------------------------------------------------------


def test_chain_integrity_emit_resolve_verify(tmp_path):
    """Emit two escalations, resolve both, verify_chain reports the chain valid."""
    from events import emit_escalation, resolve_escalation, verify_chain

    j = _journal_in(tmp_path)

    sent_a = emit_escalation(
        agent_id="gardener",
        reason="A",
        branch="constitutional",
        journal_path=j,
    )
    sent_b = emit_escalation(
        agent_id="gardener",
        reason="B",
        branch="constitutional",
        journal_path=j,
    )

    resolve_escalation(
        event_id=sent_a["event_id"],
        resolution="J applied staging",
        agent_id="gardener",
        journal_path=j,
    )
    resolve_escalation(
        event_id=sent_b["event_id"],
        resolution="J applied staging",
        agent_id="gardener",
        journal_path=j,
    )

    result = verify_chain(j)
    assert result["valid"] is True
    assert result["events"] == 4


# -----------------------------------------------------------------------
# 2. Unresolved detection — what gardener uses to find work
# -----------------------------------------------------------------------


def test_unresolved_detection_via_load_journal(tmp_path):
    """A SENT with no matching RESOLVED is detectable from load_journal alone.

    Mirrors gardener's apply_staging logic: scan the journal, build the set of
    resolved event_ids, find SENTs missing from that set.
    """
    from events import emit_escalation, load_journal

    j = _journal_in(tmp_path)
    sent = emit_escalation(
        agent_id="gardener",
        reason="needs human review",
        branch="constitutional",
        journal_path=j,
    )

    events = load_journal(j)
    resolved_ids = {
        e["event_id"] for e in events if e["event_type"] == "ESCALATION_RESOLVED"
    }
    unresolved = [
        e
        for e in events
        if e["event_type"] == "ESCALATION_SENT" and e["event_id"] not in resolved_ids
    ]

    assert len(unresolved) == 1
    assert unresolved[0]["event_id"] == sent["event_id"]


# -----------------------------------------------------------------------
# 3. Non-fatal on missing journal — required for gardener safety
# -----------------------------------------------------------------------


def test_load_journal_missing_path_is_non_fatal(tmp_path):
    """load_journal on a nonexistent path returns [] without raising.

    The gardener integration depends on this: if the journal file doesn't yet
    exist (first run), the resolve hook must not crash the gardener.
    """
    from events import load_journal

    nonexistent = str(tmp_path / "no" / "such" / "events.action.jsonl")
    assert not os.path.exists(nonexistent)

    events = load_journal(nonexistent)
    assert events == []


# -----------------------------------------------------------------------
# 4. Round-trip hash — emit, read back, recompute, equals
# -----------------------------------------------------------------------


def test_round_trip_hash_matches_recomputed(tmp_path):
    """Reading a written event back from disk and recomputing event_hash from
    its canonical-JSON payload must equal the stored event_hash."""
    from events import emit_escalation, load_journal

    j = _journal_in(tmp_path)
    emit_escalation(
        agent_id="gardener",
        reason="hash round-trip",
        branch="constitutional",
        journal_path=j,
    )

    events = load_journal(j)
    assert len(events) == 1
    ev = events[0]

    payload = {k: v for k, v in ev.items() if k != "event_hash"}
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    recomputed = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    assert recomputed == ev["event_hash"]
