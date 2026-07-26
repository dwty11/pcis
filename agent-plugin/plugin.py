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


def _ensure_paths():
    """Put the repo root AND core/ on sys.path.

    core/ is needed too, not just the root: core modules import each other
    by bare name (``from knowledge_tree import ...``), which is the repo's
    convention, so importing e.g. core.retrieval_trace fails without it.
    """
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    pcis_root = os.path.dirname(plugin_dir)
    for path in (os.path.join(pcis_root, "core"), pcis_root):
        if path not in sys.path:
            sys.path.insert(0, path)
    return pcis_root


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

    ``content`` is the leaf's FULL text. It used to be clipped to 200
    characters, which for an agent is a correctness hazard rather than a
    cosmetic one: a clip can silently drop a trailing qualifier that
    reverses the claim, and unlike a human seeing an ellipsis, an agent
    cannot tell it was handed half a sentence.

    Each retrieval is traced to the provenance ledger. A failure to record
    the trace never fails the search — see ``emit_retrieval_trace``.
    """
    if config:
        _ensure_env(config)
    _ensure_paths()

    from core.knowledge_search import search
    from core.retrieval_trace import emit_retrieval_trace

    # search() yields (score, leaf_id, leaf_data) — the id is the tuple's
    # second element, NOT a key on leaf_data (core/knowledge_search.py:307).
    results = search(query, top_k=top_k)
    mode = "semantic"
    if not results:
        # knowledge_search has already printed "keyword search is used
        # instead" — a sentence that was true for the CLI and false here,
        # so this boundary returned [] and an agent read an empty TREE
        # rather than an unavailable dependency. Worse than a wrong sentence
        # to a human, because nothing downstream can tell the two apart.
        # SAME module identity as the `search` import above: core/ is also on
        # sys.path, so `knowledge_search` and `core.knowledge_search` are two
        # distinct module objects with separate TREE_FILE/INDEX_FILE globals.
        # Mixing them would read a different tree than the caller configured.
        from core.knowledge_search import keyword_search

        results = keyword_search(query, top_k=top_k)
        mode = "keyword"

    rows = [
        {
            "score": round(score, 4),
            "leaf_id": leaf_id,
            "branch": leaf.get("branch", "?"),
            "content": leaf["content"],
            "confidence": leaf.get("confidence", 0),
        }
        for score, leaf_id, leaf in results
    ]

    # Nothing generated an answer here, so the emitted "answer" is the
    # result set itself and producer_model stays None to say so.
    emit_retrieval_trace(
        sink="pcis.retrieval-trace/agent-plugin.search",
        search_results=results,
        answer_text=json.dumps(rows, sort_keys=True, ensure_ascii=False),
        # The keyword path reads the TREE. Re-verified against that same tree
        # the comparison is self-referential, so the source must be declared or
        # search_results= would label it "index" and the reader would render a
        # verdict it has not earned.
        extras={"retrieval_mode": mode,
                "injection_source": "index" if mode == "semantic" else "tree"},
    )
    return rows


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
