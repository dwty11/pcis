#!/usr/bin/env python3
"""
action_log.py — belief-linked action log with outcome feedback.

Records what PCIS-internal agents (gardener and others) DO, ties each action
to the belief that drove it, and updates belief confidence based on outcome.
Catastrophic outcomes auto-generate COUNTER leaves on the original belief.

Append-only JSONL journal with the same SHA-256 prev_event_hash chain pattern
as core/events.py. Two event types:

    ACTION_STARTED:
        event_id, event_type, timestamp, agent_id, tool_name,
        parameters_summary, belief_id, prev_event_hash, event_hash

    ACTION_COMPLETED:
        event_id, event_type, timestamp, agent_id, action_id (= STARTED's
        event_id), outcome_severity, description, belief_id, confidence_delta,
        counter_leaf_id, prev_event_hash, event_hash

Confidence feedback rules (only when belief_id present in STARTED):
    severity < 0.3   -> +0.03 (cap 0.98)
    0.3 <= severity <= 0.6  -> no change
    severity > 0.6   -> -(0.10 * severity) (floor 0.01)
    severity > 0.8   -> additionally generate a COUNTER leaf on the same branch

All tree writes use tree_lock(). Tree-update failures are caught and the
COMPLETED event still emits — record_outcome must never crash.

Zero new dependencies outside stdlib + existing pcis core modules.
"""

import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone

# Sibling core/ modules importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


ACTION_LOG_BASENAME = "action_log.jsonl"

EVENT_TYPE_STARTED = "ACTION_STARTED"
EVENT_TYPE_COMPLETED = "ACTION_COMPLETED"


# -----------------------------------------------------------------------
# Path resolution — env-aware, evaluated per-call (mirrors events.py)
# -----------------------------------------------------------------------


def _base_dir():
    return os.environ.get(
        "PCIS_BASE_DIR",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."),
    )


def _journal_path(journal_path=None):
    if journal_path is not None:
        return journal_path
    return os.path.join(_base_dir(), "data", ACTION_LOG_BASENAME)


def _tree_path():
    return os.path.join(_base_dir(), "data", "tree.json")


# -----------------------------------------------------------------------
# Canonicalisation + hashing (same shape as core/events.py)
# -----------------------------------------------------------------------


def _canonical_json(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_event(event):
    payload = {k: v for k, v in event.items() if k != "event_hash"}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _now_iso_utc():
    return datetime.now(timezone.utc).isoformat()


def _today_iso_date():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# -----------------------------------------------------------------------
# Journal I/O
# -----------------------------------------------------------------------


def _read_lines(journal_path):
    if not os.path.exists(journal_path):
        return []
    with open(journal_path, "r", encoding="utf-8") as f:
        return [line for line in f if line.strip()]


def _last_event_hash(journal_path):
    lines = _read_lines(journal_path)
    if not lines:
        return None
    return json.loads(lines[-1]).get("event_hash")


def _append_event(journal_path, event):
    os.makedirs(os.path.dirname(os.path.abspath(journal_path)), exist_ok=True)
    with open(journal_path, "a", encoding="utf-8") as f:
        f.write(_canonical_json(event) + "\n")


# -----------------------------------------------------------------------
# Tree feedback — single tree_lock for confidence + optional counter leaf
# -----------------------------------------------------------------------


def _apply_tree_feedback(belief_id, outcome_severity, tool_name, agent_id, description):
    """Update belief confidence and optionally generate a COUNTER leaf, in
    one tree_lock() acquisition.

    Returns (confidence_delta, counter_leaf_id).
    confidence_delta is 0.0 if belief not found or no change applied.
    counter_leaf_id is None unless severity > 0.8 AND the belief was found
    AND the add_knowledge call succeeded.

    Wrapped in try/except — tree-update failure must not crash the caller.
    """
    try:
        from knowledge_tree import add_knowledge, tree_lock

        confidence_delta = 0.0
        counter_leaf_id = None

        with tree_lock(path=_tree_path()) as tree:
            target_branch = None
            target_leaf = None
            for bname, bdata in tree.get("branches", {}).items():
                for leaf in bdata.get("leaves", []):
                    if leaf.get("id") == belief_id:
                        target_branch = bname
                        target_leaf = leaf
                        break
                if target_leaf is not None:
                    break

            if target_leaf is None:
                return 0.0, None

            old_conf = float(target_leaf.get("confidence", 0.0))
            if outcome_severity < 0.3:
                new_conf = min(0.98, old_conf + 0.03)
            elif outcome_severity > 0.6:
                new_conf = max(0.01, old_conf - (0.10 * outcome_severity))
            else:
                new_conf = old_conf
            target_leaf["confidence"] = new_conf
            confidence_delta = round(new_conf - old_conf, 6)

            if outcome_severity > 0.8 and target_branch:
                try:
                    content = (
                        f"COUNTER [{belief_id}]: Action {tool_name!r} "
                        f"(agent: {agent_id}) resulted in "
                        f"outcome_severity={outcome_severity}. "
                        f"{description[:200]}"
                    )
                    counter_leaf_id = add_knowledge(
                        tree,
                        target_branch,
                        content,
                        source=f"action-outcome-{_today_iso_date()}",
                        confidence=0.65,
                    )
                except Exception:
                    counter_leaf_id = None

        return confidence_delta, counter_leaf_id
    except Exception:
        return 0.0, None


# -----------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------


def emit_action(agent_id, tool_name, parameters_summary=None, belief_id=None,
                journal_path=None):
    """Record that an agent is about to take an action.

    Returns the ACTION_STARTED event dict (with event_hash filled in).
    """
    journal = _journal_path(journal_path)
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": EVENT_TYPE_STARTED,
        "timestamp": _now_iso_utc(),
        "agent_id": agent_id,
        "tool_name": tool_name,
        "parameters_summary": parameters_summary,
        "belief_id": belief_id,
        "prev_event_hash": _last_event_hash(journal),
    }
    event["event_hash"] = _hash_event(event)
    _append_event(journal, event)
    return event


def record_outcome(action_id, outcome_severity, agent_id, description="",
                   journal_path=None):
    """Record the outcome of an action and apply belief-confidence feedback.

    Reads the journal to find the ACTION_STARTED event by action_id. The
    STARTED event's belief_id is carried into the COMPLETED event. If a
    belief is linked, confidence feedback is applied per the rules in the
    module docstring; severity > 0.8 also generates a COUNTER leaf.

    Raises ValueError if no matching ACTION_STARTED is found.
    """
    journal = _journal_path(journal_path)

    started = None
    for ev in load_action_log(journal):
        if (
            ev.get("event_id") == action_id
            and ev.get("event_type") == EVENT_TYPE_STARTED
        ):
            started = ev
            break

    if started is None:
        raise ValueError(
            f"No {EVENT_TYPE_STARTED} event with event_id={action_id!r} found "
            f"in journal {journal!r}"
        )

    belief_id = started.get("belief_id")
    confidence_delta = None
    counter_leaf_id = None

    if belief_id:
        confidence_delta, counter_leaf_id = _apply_tree_feedback(
            belief_id=belief_id,
            outcome_severity=outcome_severity,
            tool_name=started.get("tool_name", ""),
            agent_id=started.get("agent_id", ""),
            description=description,
        )

    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": EVENT_TYPE_COMPLETED,
        "timestamp": _now_iso_utc(),
        "agent_id": agent_id,
        "action_id": action_id,
        "outcome_severity": outcome_severity,
        "description": description,
        "belief_id": belief_id,
        "confidence_delta": confidence_delta,
        "counter_leaf_id": counter_leaf_id,
        "prev_event_hash": _last_event_hash(journal),
    }
    event["event_hash"] = _hash_event(event)
    _append_event(journal, event)
    return event


def load_action_log(journal_path=None):
    """Return all events from the journal in emission order. [] if no file."""
    journal = _journal_path(journal_path)
    return [json.loads(line) for line in _read_lines(journal)]


def verify_chain(journal_path=None):
    """Walk the journal and verify each event_hash + prev_event_hash link.

    Returns {"valid": bool, "length": int, "broken_at": <index | None>}.
    """
    journal = _journal_path(journal_path)
    events = load_action_log(journal)

    if not events:
        return {"valid": True, "length": 0, "broken_at": None}

    expected_prev = None
    for i, ev in enumerate(events):
        recomputed = _hash_event(ev)
        if recomputed != ev.get("event_hash"):
            return {"valid": False, "length": len(events), "broken_at": i}
        if ev.get("prev_event_hash") != expected_prev:
            return {"valid": False, "length": len(events), "broken_at": i}
        expected_prev = ev["event_hash"]

    return {"valid": True, "length": len(events), "broken_at": None}
