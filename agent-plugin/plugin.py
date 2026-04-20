#!/usr/bin/env python3
"""
PCIS Agent Plugin — gives any compatible agent persistent, verified memory.

On session start: runs ``pcis verify`` and loads tree status.
Provides three tools for the agent:
    pcis_add(branch, content, source, confidence)
    pcis_search(query, top_k)
    pcis_status()

Configuration (via plugin.json):
    base_dir      — PCIS data directory (default: ~/.pcis)
    auto_capture  — auto-extract knowledge from conversations (default: true)
"""

import json
import os
import subprocess
import sys

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _resolve_base_dir(config):
    """Return the absolute PCIS base directory from plugin config."""
    raw = config.get("base_dir", "~/.pcis")
    return os.path.expanduser(raw)


def _ensure_env(config):
    """Set PCIS_BASE_DIR so all core imports pick up the right directory."""
    base_dir = _resolve_base_dir(config)
    os.environ["PCIS_BASE_DIR"] = base_dir
    return base_dir


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

def on_session_start(config):
    """Called by the agent framework when a session begins.

    Verifies tree integrity and returns a status summary dict.
    """
    base_dir = _ensure_env(config)

    # Ensure core/ is importable
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    pcis_root = os.path.dirname(plugin_dir)
    sys.path.insert(0, os.path.join(pcis_root, "core"))
    sys.path.insert(0, pcis_root)

    from core.knowledge_tree import load_tree, compute_root_hash

    tree = load_tree()
    stored = tree.get("root_hash", "")
    computed = compute_root_hash(tree)
    branches = tree.get("branches", {})
    total_leaves = sum(len(b.get("leaves", [])) for b in branches.values())

    return {
        "base_dir": base_dir,
        "integrity": "clean" if stored == computed else "mismatch",
        "root_hash": computed[:24],
        "branches": len(branches),
        "leaves": total_leaves,
    }


# ---------------------------------------------------------------------------
# Agent tools
# ---------------------------------------------------------------------------

def pcis_add(branch, content, source="agent-plugin", confidence=0.8, config=None):
    """Add a knowledge leaf to the tree.

    Args:
        branch: Target branch name (e.g. "technical", "lessons").
        content: The knowledge content string.
        source: Source attribution.
        confidence: Confidence level (0.0 - 1.0).
        config: Plugin config dict (optional if PCIS_BASE_DIR already set).

    Returns:
        dict with leaf_id, branch, and root_hash.
    """
    if config:
        _ensure_env(config)

    from core.knowledge_tree import tree_lock, compute_root_hash

    with tree_lock() as tree:
        from core.knowledge_tree import add_knowledge
        leaf_id = add_knowledge(tree, branch, content, source=source, confidence=confidence)

    from core.knowledge_tree import load_tree
    tree = load_tree()
    return {
        "leaf_id": leaf_id,
        "branch": branch,
        "root_hash": compute_root_hash(tree)[:24],
    }


def pcis_search(query, top_k=5, config=None):
    """Search the knowledge tree.

    Args:
        query: Search query string.
        top_k: Maximum number of results to return.
        config: Plugin config dict (optional).

    Returns:
        List of dicts with score, leaf_id, branch, content, and confidence.
    """
    if config:
        _ensure_env(config)

    from core.knowledge_search import search

    results = search(query, top_k=top_k)
    return [
        {
            "score": round(score, 4),
            "leaf_id": leaf["id"],
            "branch": leaf.get("branch", "?"),
            "content": leaf["content"][:200],
            "confidence": leaf.get("confidence", 0),
        }
        for score, leaf in results
    ]


def pcis_status(config=None):
    """Return current tree status.

    Returns:
        dict with leaves, branches, root_hash, integrity, and per-branch counts.
    """
    if config:
        _ensure_env(config)

    from core.knowledge_tree import load_tree, compute_root_hash

    tree = load_tree()
    stored = tree.get("root_hash", "")
    computed = compute_root_hash(tree)
    branches = tree.get("branches", {})

    branch_counts = {
        name: len(data.get("leaves", []))
        for name, data in sorted(branches.items())
    }

    return {
        "leaves": sum(branch_counts.values()),
        "branches": len(branches),
        "branch_counts": branch_counts,
        "root_hash": computed[:24],
        "integrity": "clean" if stored == computed else "mismatch",
    }
