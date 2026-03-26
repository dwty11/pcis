#!/usr/bin/env python3
"""
belief_updater.py — Bayesian Belief Updating Engine

When new evidence arrives (a synapse is added), this module updates the
target leaf's confidence using a simple Bayesian-inspired formula:

  SUPPORTS:    P(H|E) = P(H) + (1 - P(H)) * 0.15
  CONTRADICTS: P(H|E) = P(H) * 0.80

Caps: confidence never goes below 0.05 or above 0.98.

Every update is logged to data/belief-updates.json (append-only) and
the full Merkle hash chain (leaf -> branch -> root) is recomputed.

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
UPDATE_LOG_FILE = os.path.join(BASE_DIR, "data", "belief-updates.json")

TZ_UTC = timezone.utc

# --- Bayesian update constants -------------------------------------------

SUPPORT_BOOST = 0.15   # P(H|E) = P(H) + (1 - P(H)) * 0.15
CONTRADICT_FACTOR = 0.80  # P(H|E) = P(H) * 0.80
CONFIDENCE_MIN = 0.05
CONFIDENCE_MAX = 0.98


# --- Update log ----------------------------------------------------------

def _load_update_log(log_file=None):
    log_file = log_file or UPDATE_LOG_FILE
    if os.path.exists(log_file):
        try:
            with open(log_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []


def _save_update_log(entries, log_file=None):
    log_file = log_file or UPDATE_LOG_FILE
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    tmp = log_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
    os.replace(tmp, log_file)


def get_update_log(log_file=None):
    """Return the full update log as a list of dicts."""
    return _load_update_log(log_file)


# --- Core update logic ---------------------------------------------------

def _apply_update(old_confidence, relation):
    """Apply the Bayesian formula. Returns new confidence (clamped)."""
    if relation == "SUPPORTS":
        new = old_confidence + (1 - old_confidence) * SUPPORT_BOOST
    elif relation == "CONTRADICTS":
        new = old_confidence * CONTRADICT_FACTOR
    else:
        return old_confidence  # other relations don't trigger updates

    return max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, round(new, 10)))


def _find_leaf_in_tree(tree, leaf_id):
    """Find leaf by ID. Returns (branch_name, leaf) or (None, None)."""
    for branch_name, branch in tree.get("branches", {}).items():
        for leaf in branch.get("leaves", []):
            if leaf["id"] == leaf_id:
                return branch_name, leaf
    return None, None


def _rehash_leaf_and_chain(tree, branch_name, leaf):
    """Recompute leaf hash, branch hash, and root hash."""
    from core.knowledge_tree import hash_leaf, compute_branch_hash, compute_root_hash

    leaf["hash"] = hash_leaf(leaf["content"], branch_name, leaf["created"])
    tree["branches"][branch_name]["hash"] = compute_branch_hash(
        tree["branches"][branch_name]["leaves"]
    )
    tree["root_hash"] = compute_root_hash(tree)


def update_from_synapse(synapse, tree, log_file=None, history_file=None):
    """Apply Bayesian update to the target leaf of a synapse.

    Only SUPPORTS and CONTRADICTS relations trigger an update.
    The update is applied to the *to_leaf* (the leaf being supported/contradicted).

    Returns a dict describing the change, or None if no update was needed.
    """
    relation = synapse.get("relation", "")
    if relation not in ("SUPPORTS", "CONTRADICTS"):
        return None

    target_id = synapse["to_leaf"]
    branch_name, leaf = _find_leaf_in_tree(tree, target_id)

    if leaf is None:
        logger.warning(
            "belief_updater: target leaf %s not found, skipping update.", target_id
        )
        return None

    old_confidence = leaf["confidence"]
    new_confidence = _apply_update(old_confidence, relation)

    if old_confidence == new_confidence:
        return None

    # Write the updated confidence back to the tree
    leaf["confidence"] = new_confidence

    # Recompute full Merkle hash chain
    _rehash_leaf_and_chain(tree, branch_name, leaf)

    # Build log entry
    timestamp = datetime.now(TZ_UTC).strftime("%Y-%m-%dT%H:%M:%S UTC")
    synapse_id = synapse.get("id", "unknown")
    entry = {
        "leaf_id": target_id,
        "old_confidence": round(old_confidence, 10),
        "new_confidence": round(new_confidence, 10),
        "reason": f"{relation} synapse {synapse_id}",
        "timestamp": timestamp,
    }

    # Append to log
    log = _load_update_log(log_file)
    log.append(entry)
    _save_update_log(log, log_file)

    # Record in belief history
    try:
        from core.belief_history import record_change
        record_change(
            target_id, "confidence_update",
            round(old_confidence, 10), round(new_confidence, 10),
            f"{relation} synapse {synapse_id}",
            tree, history_file=history_file,
        )
    except Exception:
        pass  # history is advisory; don't break the update

    return entry


def recompute_all(tree, synapses=None, log_file=None):
    """Recompute confidence for all leaves affected by synapses, from scratch.

    Resets each affected leaf to its *original base confidence* (before any
    Bayesian updates) — which we approximate as 0.7 for leaves that lack a
    recorded original — then replays every synapse in chronological order.

    Returns {"updated": N, "changes": [...]}.
    """
    if synapses is None:
        from core.knowledge_synapses import load_synapses
        synapses = load_synapses()

    all_synapses = synapses.get("synapses", [])

    # Collect all leaves that are targets of SUPPORTS or CONTRADICTS edges.
    affected_ids = set()
    for s in all_synapses:
        if s["relation"] in ("SUPPORTS", "CONTRADICTS"):
            affected_ids.add(s["to_leaf"])

    # Snapshot original confidences so we can reset before replaying
    originals = {}
    for leaf_id in affected_ids:
        branch_name, leaf = _find_leaf_in_tree(tree, leaf_id)
        if leaf is not None:
            originals[leaf_id] = (branch_name, leaf, leaf["confidence"])

    # Reset affected leaves to base confidence (undo prior Bayesian updates).
    # We use 0.7 as the neutral default — matches add_knowledge() default.
    # If the leaf has never been updated, this is a no-op.
    log = _load_update_log(log_file)
    prior_updates_for = {}
    for entry in log:
        lid = entry["leaf_id"]
        if lid not in prior_updates_for:
            prior_updates_for[lid] = entry.get("old_confidence", 0.7)
    # The very first old_confidence in the log for each leaf is its pre-update base.
    for leaf_id in affected_ids:
        _, leaf = _find_leaf_in_tree(tree, leaf_id)
        if leaf is not None:
            if leaf_id in prior_updates_for:
                leaf["confidence"] = prior_updates_for[leaf_id]
            # else: leave as-is (not previously updated)

    # Sort synapses chronologically, then replay
    sorted_synapses = sorted(all_synapses, key=lambda s: s.get("created", ""))
    changes = []
    for s in sorted_synapses:
        if s["relation"] not in ("SUPPORTS", "CONTRADICTS"):
            continue
        target_id = s["to_leaf"]
        branch_name, leaf = _find_leaf_in_tree(tree, target_id)
        if leaf is None:
            continue

        old_conf = leaf["confidence"]
        new_conf = _apply_update(old_conf, s["relation"])

        if old_conf != new_conf:
            leaf["confidence"] = new_conf
            _rehash_leaf_and_chain(tree, branch_name, leaf)

            timestamp = datetime.now(TZ_UTC).strftime("%Y-%m-%dT%H:%M:%S UTC")
            entry = {
                "leaf_id": target_id,
                "old_confidence": round(old_conf, 10),
                "new_confidence": round(new_conf, 10),
                "reason": f"recompute: {s['relation']} synapse {s.get('id', '?')}",
                "timestamp": timestamp,
            }
            log.append(entry)
            changes.append(entry)

    _save_update_log(log, log_file)

    return {"updated": len(changes), "changes": changes}
