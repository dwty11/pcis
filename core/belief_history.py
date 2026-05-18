#!/usr/bin/env python3
"""
belief_history.py — Version History for Knowledge Leaves

Every change to a leaf's confidence, content, or source is recorded as an
append-only versioned record in data/belief-history.json.  Think git commits
for beliefs: who changed it, why, when, and what the hash was before and after.

No external dependencies. Python 3.8+.
"""

import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

BASE_DIR = os.environ.get(
    "PCIS_BASE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."),
)
HISTORY_FILE = os.path.join(BASE_DIR, "data", "belief-history.json")

TZ_UTC = timezone.utc

VALID_CHANGE_TYPES = {
    "confidence_update",
    "content_edit",
    "source_update",
    "created",
    "decayed",
}


# --- Persistence -----------------------------------------------------------

def _load_history(history_file=None):
    history_file = history_file or HISTORY_FILE
    if os.path.exists(history_file):
        try:
            with open(history_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []


def _save_history(records, history_file=None):
    history_file = history_file or HISTORY_FILE
    os.makedirs(os.path.dirname(history_file), exist_ok=True)
    tmp = history_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
    os.replace(tmp, history_file)


# --- Public API ------------------------------------------------------------

def record_change(leaf_id, change_type, old_value, new_value, reason, tree,
                  history_file=None):
    """Append a versioned change record for a leaf.

    Parameters
    ----------
    leaf_id : str
    change_type : str
        One of: confidence_update, content_edit, source_update, created, decayed
    old_value : any
        The previous value (confidence float, content string, etc.)
    new_value : any
        The new value
    reason : str
        Human-readable reason (e.g. "SUPPORTS synapse abc123")
    tree : dict
        The current knowledge tree (used to look up leaf hash)
    history_file : str | None
        Override path for testing

    Returns
    -------
    dict  — the record that was appended
    """
    if change_type not in VALID_CHANGE_TYPES:
        raise ValueError(
            f"Invalid change_type '{change_type}'. "
            f"Must be one of: {VALID_CHANGE_TYPES}"
        )

    # Look up current leaf to get hash context
    leaf_hash_before = ""
    leaf_hash_after = ""
    for branch in tree.get("branches", {}).values():
        for leaf in branch.get("leaves", []):
            if leaf["id"] == leaf_id:
                leaf_hash_after = leaf.get("hash", "")
                break

    # For confidence_update / decayed the hash doesn't change (confidence
    # isn't part of hash_leaf), so before == after.  For content_edit the
    # caller should pass the tree *after* rehashing, so hash_after is the
    # new one.  We store old_value which lets us reconstruct.
    if change_type in ("confidence_update", "decayed"):
        leaf_hash_before = leaf_hash_after  # hash unchanged
    else:
        # For content edits the hash will differ; caller is responsible for
        # having rehashed. We can only capture the *after* hash here.
        leaf_hash_before = ""  # unknown — would need the pre-edit tree

    timestamp = datetime.now(TZ_UTC).strftime("%Y-%m-%dT%H:%M:%S UTC")

    record = {
        "leaf_id": leaf_id,
        "change_type": change_type,
        "old_value": old_value,
        "new_value": new_value,
        "reason": reason,
        "leaf_hash_before": leaf_hash_before,
        "leaf_hash_after": leaf_hash_after,
        "timestamp": timestamp,
    }

    history = _load_history(history_file)
    history.append(record)
    _save_history(history, history_file)

    return record


def get_leaf_history(leaf_id, history_file=None):
    """Return all version records for a leaf, in chronological order."""
    history = _load_history(history_file)
    return [r for r in history if r["leaf_id"] == leaf_id]


def get_recent_changes(n=20, history_file=None):
    """Return the N most recent changes across all leaves (newest first)."""
    history = _load_history(history_file)
    # History is append-only / chronological, so the last N are the most recent.
    return list(reversed(history[-n:]))


def diff_versions(leaf_id, v1_index, v2_index, history_file=None):
    """Return a diff between two version records of a leaf.

    v1_index and v2_index are 0-based indices into the leaf's history
    (as returned by get_leaf_history).

    Returns a dict showing what changed between the two versions.
    """
    leaf_records = get_leaf_history(leaf_id, history_file)

    if not leaf_records:
        return {"error": f"No history found for leaf {leaf_id}"}

    if v1_index < 0 or v1_index >= len(leaf_records):
        return {"error": f"v1 index {v1_index} out of range (0–{len(leaf_records) - 1})"}
    if v2_index < 0 or v2_index >= len(leaf_records):
        return {"error": f"v2 index {v2_index} out of range (0–{len(leaf_records) - 1})"}

    v1 = leaf_records[v1_index]
    v2 = leaf_records[v2_index]

    return {
        "leaf_id": leaf_id,
        "v1_index": v1_index,
        "v2_index": v2_index,
        "v1": v1,
        "v2": v2,
        "changes": {
            "change_type": [v1["change_type"], v2["change_type"]],
            "old_value": [v1["old_value"], v2["old_value"]],
            "new_value": [v1["new_value"], v2["new_value"]],
            "reason": [v1["reason"], v2["reason"]],
            "timestamp": [v1["timestamp"], v2["timestamp"]],
            "leaf_hash_before": [v1["leaf_hash_before"], v2["leaf_hash_before"]],
            "leaf_hash_after": [v1["leaf_hash_after"], v2["leaf_hash_after"]],
        },
    }
