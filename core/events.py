#!/usr/bin/env python3
"""
events.py — Hash-chained ESCALATION event journal.

Records events PCIS emits when an AI agent flags a decision for human
review (ESCALATION_SENT) and when that review completes (ESCALATION_RESOLVED).

The journal is an append-only JSONL file (one canonical-JSON event per
line). Each event carries a SHA-256 hash of its own canonicalised
payload, plus a prev_event_hash linking it to the previous event in the
journal — a tamper-evident chain that can be verified offline.

No external dependencies. Python 3.10+.

Schema (one JSON object per journal line):

    {
      "event_id":         "<uuid4>",
      "event_type":       "ESCALATION_SENT" | "ESCALATION_RESOLVED",
      "timestamp":        "<ISO 8601 UTC>",
      "agent_id":         "<string>",
      "leaf_id":          "<string | null>",
      "branch":           "<string | null>",
      "reason":           "<string>",
      "resolution":       "<string | null>",   # populated on RESOLVED only
      "prev_event_hash":  "<sha256 hex | null>",
      "event_hash":       "<sha256 hex>"
    }

Public API:
    emit_escalation(agent_id, reason, leaf_id=None, branch=None, journal_path=None)
    resolve_escalation(event_id, resolution, agent_id, journal_path=None)
    load_journal(journal_path=None)
    verify_chain(journal_path=None)
"""

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone


# -----------------------------------------------------------------------
# Path resolution — mirrors the pattern used by core/signing.py
# -----------------------------------------------------------------------


def _base_dir():
    return os.environ.get(
        "PCIS_BASE_DIR",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."),
    )


DEFAULT_JOURNAL_BASENAME = "events.action.jsonl"

EVENT_TYPE_SENT = "ESCALATION_SENT"
EVENT_TYPE_RESOLVED = "ESCALATION_RESOLVED"


def _journal_path(journal_path=None):
    if journal_path is not None:
        return journal_path
    return os.path.join(_base_dir(), "data", DEFAULT_JOURNAL_BASENAME)


# -----------------------------------------------------------------------
# Canonicalisation + hashing
# -----------------------------------------------------------------------


def _canonical_json(payload):
    """Canonical JSON for hashing — keys sorted, no whitespace, UTF-8."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _hash_event(event):
    """SHA-256 of the canonicalised event payload, excluding the event_hash field."""
    payload = {k: v for k, v in event.items() if k != "event_hash"}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _now_iso_utc():
    """ISO 8601 timestamp in UTC, suitable for the journal."""
    return datetime.now(timezone.utc).isoformat()


# -----------------------------------------------------------------------
# Journal I/O
# -----------------------------------------------------------------------


def _read_lines(journal_path):
    if not os.path.exists(journal_path):
        return []
    with open(journal_path, "r", encoding="utf-8") as f:
        return [line for line in f if line.strip()]


def _last_event_hash(journal_path):
    """Return the event_hash of the most recent event, or None if journal is empty."""
    lines = _read_lines(journal_path)
    if not lines:
        return None
    last = json.loads(lines[-1])
    return last.get("event_hash")


def _append_event(journal_path, event):
    os.makedirs(os.path.dirname(os.path.abspath(journal_path)), exist_ok=True)
    with open(journal_path, "a", encoding="utf-8") as f:
        f.write(_canonical_json(event) + "\n")


def _build_event(event_type, agent_id, reason, leaf_id, branch,
                 resolution, prev_event_hash):
    """Construct an event dict with event_hash filled in."""
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "timestamp": _now_iso_utc(),
        "agent_id": agent_id,
        "leaf_id": leaf_id,
        "branch": branch,
        "reason": reason,
        "resolution": resolution,
        "prev_event_hash": prev_event_hash,
    }
    event["event_hash"] = _hash_event(event)
    return event


# -----------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------


def emit_escalation(agent_id, reason, leaf_id=None, branch=None,
                    journal_path=None):
    """Emit an ESCALATION_SENT event.

    Returns the event dict (with event_hash filled in) and appends it to
    the journal.
    """
    journal = _journal_path(journal_path)
    event = _build_event(
        event_type=EVENT_TYPE_SENT,
        agent_id=agent_id,
        reason=reason,
        leaf_id=leaf_id,
        branch=branch,
        resolution=None,
        prev_event_hash=_last_event_hash(journal),
    )
    _append_event(journal, event)
    return event


def resolve_escalation(event_id, resolution, agent_id, journal_path=None):
    """Emit an ESCALATION_RESOLVED event referencing a prior ESCALATION_SENT.

    Reads the journal, finds the SENT event by event_id, copies forward
    its leaf_id / branch / reason as context, and appends a new RESOLVED
    event with the supplied resolution.

    Raises ValueError if no matching ESCALATION_SENT is found.
    """
    journal = _journal_path(journal_path)

    sent = None
    for ev in load_journal(journal):
        if (
            ev.get("event_id") == event_id
            and ev.get("event_type") == EVENT_TYPE_SENT
        ):
            sent = ev
            break

    if sent is None:
        raise ValueError(
            f"No {EVENT_TYPE_SENT} event with event_id={event_id!r} found in journal"
        )

    event = _build_event(
        event_type=EVENT_TYPE_RESOLVED,
        agent_id=agent_id,
        reason=sent.get("reason"),
        leaf_id=sent.get("leaf_id"),
        branch=sent.get("branch"),
        resolution=resolution,
        prev_event_hash=_last_event_hash(journal),
    )
    _append_event(journal, event)
    return event


def load_journal(journal_path=None):
    """Return the journal as a list of event dicts in emission order."""
    journal = _journal_path(journal_path)
    return [json.loads(line) for line in _read_lines(journal)]


def verify_chain(journal_path=None):
    """Walk the journal, verify each event_hash and prev_event_hash link.

    Returns {"valid": bool, "events": int, "detail": str}.
    """
    journal = _journal_path(journal_path)
    events = load_journal(journal)

    if not events:
        return {"valid": True, "events": 0, "detail": "journal is empty"}

    expected_prev = None
    for i, ev in enumerate(events):
        recomputed = _hash_event(ev)
        stored = ev.get("event_hash")
        if recomputed != stored:
            return {
                "valid": False,
                "events": len(events),
                "detail": (
                    f"event {i} ({ev.get('event_id')}): event_hash mismatch — "
                    f"stored {stored[:16]}…  expected {recomputed[:16]}…"
                ),
            }
        if ev.get("prev_event_hash") != expected_prev:
            return {
                "valid": False,
                "events": len(events),
                "detail": (
                    f"event {i} ({ev.get('event_id')}): prev_event_hash mismatch — "
                    f"got {ev.get('prev_event_hash')!r}  expected {expected_prev!r}"
                ),
            }
        expected_prev = stored

    return {
        "valid": True,
        "events": len(events),
        "detail": f"chain verified across {len(events)} events",
    }
