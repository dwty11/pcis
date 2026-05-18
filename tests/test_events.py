#!/usr/bin/env python3
"""Tests for core/events.py — ESCALATION event journal."""

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


@pytest.fixture
def tmp_journal(tmp_path, monkeypatch):
    """Set PCIS_BASE_DIR to a tmp dir; expose its default journal path."""
    monkeypatch.setenv("PCIS_BASE_DIR", str(tmp_path))
    journal = tmp_path / "data" / "events.action.jsonl"
    return str(journal)


# -----------------------------------------------------------------------
# emit_escalation
# -----------------------------------------------------------------------


def test_emit_escalation_returns_valid_event(tmp_journal):
    from events import emit_escalation

    ev = emit_escalation(
        agent_id="agent_a",
        reason="confidence below threshold",
        leaf_id="leaf-abc",
        branch="lessons",
        journal_path=tmp_journal,
    )

    assert ev["event_id"]
    assert ev["event_type"] == "ESCALATION_SENT"
    assert ev["timestamp"]
    assert ev["agent_id"] == "agent_a"
    assert ev["leaf_id"] == "leaf-abc"
    assert ev["branch"] == "lessons"
    assert ev["reason"] == "confidence below threshold"
    assert ev["resolution"] is None
    assert ev["prev_event_hash"] is None  # first event in journal
    assert ev["event_hash"]
    assert len(ev["event_hash"]) == 64  # sha256 hex


def test_event_hash_is_reproducible(tmp_journal):
    """Recomputing the hash from the event dict (minus event_hash field)
    must reproduce the stored event_hash. This is canonical-JSON determinism."""
    from events import emit_escalation

    ev = emit_escalation(
        agent_id="agent_a", reason="r", journal_path=tmp_journal
    )
    payload = {k: v for k, v in ev.items() if k != "event_hash"}
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    expected = hashlib.sha256(canonical.encode()).hexdigest()
    assert ev["event_hash"] == expected


# -----------------------------------------------------------------------
# resolve_escalation
# -----------------------------------------------------------------------


def test_resolve_escalation_links_to_sent(tmp_journal):
    from events import emit_escalation, resolve_escalation

    sent = emit_escalation(
        agent_id="agent_a",
        reason="needs human review",
        leaf_id="leaf-xyz",
        branch="identity",
        journal_path=tmp_journal,
    )

    resolved = resolve_escalation(
        event_id=sent["event_id"],
        resolution="human approved the proposed change",
        agent_id="J",
        journal_path=tmp_journal,
    )

    assert resolved["event_type"] == "ESCALATION_RESOLVED"
    assert resolved["event_id"] != sent["event_id"]  # new identity
    assert resolved["agent_id"] == "J"
    # Carries forward context from SENT
    assert resolved["leaf_id"] == "leaf-xyz"
    assert resolved["branch"] == "identity"
    assert resolved["reason"] == "needs human review"
    # Resolution is now populated
    assert resolved["resolution"] == "human approved the proposed change"
    # Chain link: prev_event_hash points to the SENT (it's the only prior event)
    assert resolved["prev_event_hash"] == sent["event_hash"]


def test_resolve_unknown_event_id_raises(tmp_journal):
    from events import resolve_escalation

    with pytest.raises(ValueError):
        resolve_escalation(
            event_id="does-not-exist",
            resolution="...",
            agent_id="J",
            journal_path=tmp_journal,
        )


# -----------------------------------------------------------------------
# load_journal
# -----------------------------------------------------------------------


def test_load_journal_returns_in_order(tmp_journal):
    from events import emit_escalation, load_journal

    a = emit_escalation(agent_id="agent_a", reason="A", journal_path=tmp_journal)
    b = emit_escalation(agent_id="agent_a", reason="B", journal_path=tmp_journal)
    c = emit_escalation(agent_id="agent_a", reason="C", journal_path=tmp_journal)

    events = load_journal(tmp_journal)
    assert len(events) == 3
    assert events[0]["event_id"] == a["event_id"]
    assert events[1]["event_id"] == b["event_id"]
    assert events[2]["event_id"] == c["event_id"]


def test_load_journal_empty_when_no_file(tmp_journal):
    from events import load_journal

    events = load_journal(tmp_journal)
    assert events == []


# -----------------------------------------------------------------------
# verify_chain
# -----------------------------------------------------------------------


def test_verify_chain_passes_on_intact_chain(tmp_journal):
    from events import emit_escalation, verify_chain

    emit_escalation(agent_id="agent_a", reason="A", journal_path=tmp_journal)
    emit_escalation(agent_id="agent_a", reason="B", journal_path=tmp_journal)

    result = verify_chain(tmp_journal)
    assert result["valid"] is True
    assert result["events"] == 2


def test_verify_chain_fails_if_event_tampered(tmp_journal):
    """Modify an event's content after-the-fact — verify must fail."""
    from events import emit_escalation, verify_chain

    emit_escalation(agent_id="agent_a", reason="original", journal_path=tmp_journal)

    # Tamper: read journal, change reason, write back
    with open(tmp_journal, "r") as f:
        line = f.readline()
    ev = json.loads(line)
    ev["reason"] = "tampered"
    with open(tmp_journal, "w") as f:
        f.write(json.dumps(ev) + "\n")

    result = verify_chain(tmp_journal)
    assert result["valid"] is False


def test_verify_chain_fails_if_prev_link_wrong(tmp_journal):
    from events import emit_escalation, verify_chain

    emit_escalation(agent_id="agent_a", reason="A", journal_path=tmp_journal)
    emit_escalation(agent_id="agent_a", reason="B", journal_path=tmp_journal)

    # Tamper: read both events, swap the second's prev_event_hash
    with open(tmp_journal, "r") as f:
        lines = f.readlines()
    ev_b = json.loads(lines[1])
    ev_b["prev_event_hash"] = "0" * 64  # bad link
    # Recompute event_hash so we don't fail on event_hash check first
    payload = {k: v for k, v in ev_b.items() if k != "event_hash"}
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    ev_b["event_hash"] = hashlib.sha256(canonical.encode()).hexdigest()
    lines[1] = json.dumps(ev_b) + "\n"
    with open(tmp_journal, "w") as f:
        f.writelines(lines)

    result = verify_chain(tmp_journal)
    assert result["valid"] is False


def test_verify_chain_empty_journal(tmp_journal):
    from events import verify_chain

    result = verify_chain(tmp_journal)
    assert result["valid"] is True
    assert result["events"] == 0


# -----------------------------------------------------------------------
# Default path resolution
# -----------------------------------------------------------------------


def test_journal_path_defaults_under_pcis_base_dir(tmp_path, monkeypatch):
    """When journal_path=None, events should land under
    <PCIS_BASE_DIR>/data/events.action.jsonl."""
    monkeypatch.setenv("PCIS_BASE_DIR", str(tmp_path))
    from events import emit_escalation

    emit_escalation(agent_id="agent_a", reason="default-path test")

    expected = tmp_path / "data" / "events.action.jsonl"
    assert expected.exists(), f"Default journal should land at {expected}"


# -----------------------------------------------------------------------
# Chain semantics
# -----------------------------------------------------------------------


def test_two_escalations_chain_correctly(tmp_journal):
    """Second event's prev_event_hash must equal first event's event_hash."""
    from events import emit_escalation

    a = emit_escalation(agent_id="agent_a", reason="first", journal_path=tmp_journal)
    b = emit_escalation(agent_id="agent_a", reason="second", journal_path=tmp_journal)

    assert a["prev_event_hash"] is None  # first in chain
    assert b["prev_event_hash"] == a["event_hash"]
