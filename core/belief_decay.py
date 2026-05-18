#!/usr/bin/env python3
"""
belief_decay.py — Time-based confidence decay for the knowledge tree.

Beliefs degrade over time unless refreshed. Exponential half-life decay:
    decayed = original * (0.5 ** (age_days / half_life_days))

Exempt branches:
    - constraints: behavioral rules must not degrade
    - state: current facts are replaced or removed, not decayed
"""

import json
import os
from datetime import datetime, timezone

from core.knowledge_tree import (
    TREE_FILE,
    hash_leaf,
    load_tree,
    save_tree,
)

EXEMPT_BRANCHES = {"constraints", "state"}


def decay_confidence(leaf, half_life_days=180, now=None):
    """Compute decayed confidence for a single leaf.

    Returns (decayed_confidence, age_days).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    created_str = leaf["created"]
    # Parse "YYYY-MM-DD HH:MM:SS UTC" format
    created = datetime.strptime(created_str, "%Y-%m-%d %H:%M:%S UTC").replace(
        tzinfo=timezone.utc
    )
    age_days = (now - created).total_seconds() / 86400.0
    if age_days <= 0:
        return leaf["confidence"], 0.0
    original = leaf["confidence"]
    decayed = original * (0.5 ** (age_days / half_life_days))
    return round(decayed, 6), round(age_days, 2)


def apply_decay_to_tree(tree_path=None, half_life_days=180, dry_run=False, now=None,
                        history_file=None):
    """Apply confidence decay to every non-exempt leaf in the tree.

    Returns a summary dict:
        updated: int — number of leaves whose confidence changed
        skipped: int — number of leaves in exempt branches
        total: int — total leaves processed
        min_decay: float — smallest confidence drop
        max_decay: float — largest confidence drop
        avg_decay: float — average confidence drop
    """
    tree_path = tree_path or TREE_FILE
    tree = load_tree(tree_path)

    updated = 0
    skipped = 0
    total = 0
    drops = []
    decayed_leaves = []  # (leaf_id, old_conf, new_conf) for history

    for branch_name, branch in tree.get("branches", {}).items():
        for leaf in branch.get("leaves", []):
            total += 1
            if branch_name in EXEMPT_BRANCHES:
                skipped += 1
                continue
            old_conf = leaf["confidence"]
            new_conf, age_days = decay_confidence(
                leaf, half_life_days=half_life_days, now=now
            )
            if new_conf < old_conf:
                drop = old_conf - new_conf
                drops.append(drop)
                leaf["confidence"] = new_conf
                # Recompute leaf hash with updated confidence
                # Note: confidence is not part of the hash (hash = branch:timestamp:content)
                # but we still count it as updated
                updated += 1
                decayed_leaves.append((leaf["id"], old_conf, new_conf))

    summary = {
        "updated": updated,
        "skipped": skipped,
        "total": total,
        "min_decay": round(min(drops), 6) if drops else 0.0,
        "max_decay": round(max(drops), 6) if drops else 0.0,
        "avg_decay": round(sum(drops) / len(drops), 6) if drops else 0.0,
    }

    if not dry_run and updated > 0:
        save_tree(tree, tree_path)

        # Record each decayed leaf in belief history
        try:
            from core.belief_history import record_change
            for leaf_id, old_c, new_c in decayed_leaves:
                record_change(
                    leaf_id, "decayed",
                    round(old_c, 6), round(new_c, 6),
                    f"time decay (half-life {half_life_days}d)",
                    tree, history_file=history_file,
                )
        except Exception:
            pass  # history is advisory

    return summary


def decay_report(tree_path=None, half_life_days=180, now=None):
    """Generate a per-leaf decay report without modifying the tree.

    Returns a list of dicts with keys:
        leaf_id, branch, content_preview, old_conf, new_conf, age_days
    """
    tree_path = tree_path or TREE_FILE
    tree = load_tree(tree_path)
    report = []

    for branch_name, branch in tree.get("branches", {}).items():
        for leaf in branch.get("leaves", []):
            if branch_name in EXEMPT_BRANCHES:
                continue
            old_conf = leaf["confidence"]
            new_conf, age_days = decay_confidence(
                leaf, half_life_days=half_life_days, now=now
            )
            report.append({
                "leaf_id": leaf["id"],
                "branch": branch_name,
                "content_preview": leaf["content"][:60],
                "old_conf": round(old_conf, 6),
                "new_conf": round(new_conf, 6),
                "age_days": age_days,
            })

    return report


def decay_status(tree_path=None, half_life_days=180, now=None):
    """Check how many leaves fall below confidence thresholds.

    Does NOT modify the tree — read-only analysis.

    Returns a dict:
        total: int
        exempt: int
        thresholds: {0.5: int, 0.3: int, 0.1: int}  — counts below each
    """
    tree_path = tree_path or TREE_FILE
    tree = load_tree(tree_path)

    total = 0
    exempt = 0
    below = {0.5: 0, 0.3: 0, 0.1: 0}

    for branch_name, branch in tree.get("branches", {}).items():
        for leaf in branch.get("leaves", []):
            total += 1
            if branch_name in EXEMPT_BRANCHES:
                exempt += 1
                continue
            new_conf, _ = decay_confidence(
                leaf, half_life_days=half_life_days, now=now
            )
            for threshold in below:
                if new_conf < threshold:
                    below[threshold] += 1

    return {
        "total": total,
        "exempt": exempt,
        "thresholds": below,
    }
