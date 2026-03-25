#!/usr/bin/env python3
"""
belief_traversal.py — PCIS Belief Traversal Engine

Walks the synapse graph to compute net confidence for any knowledge leaf,
accounting for supporting evidence, contradictions, supersessions, and depth decay.

No external dependencies. Python 3.8+.
"""

import os
import sys

WORKSPACE = os.environ.get("PCIS_BASE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# Tunable constants — v2.0 will replace with proper Bayesian posteriors.
SUPPORT_WEIGHT = 0.1
CONTRADICTION_WEIGHT = 0.15
DEPTH_DECAY = 0.5  # applied per hop beyond depth 1

# Relation-specific weight multiplier
WEAK_RELATIONS = {"REFINES", "DERIVES_FROM"}
WEAK_MULTIPLIER = 0.5


def _find_leaf(tree, leaf_id):
    """Find a leaf by ID across all branches. Returns (branch_name, leaf) or (None, None)."""
    for branch_name, branch in tree.get("branches", {}).items():
        for leaf in branch.get("leaves", []):
            if leaf["id"] == leaf_id:
                return branch_name, leaf
    return None, None


def _get_synapses_for_leaf(synapses, leaf_id):
    """Return all synapses touching this leaf."""
    return [
        s for s in synapses.get("synapses", [])
        if s["from_leaf"] == leaf_id or s["to_leaf"] == leaf_id
    ]


def assess_belief(leaf_id, tree=None, synapses=None, max_depth=3):
    """Assess net confidence for a leaf by traversing its synapse graph."""
    # Load tree if not provided
    if tree is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from knowledge_tree import load_tree
        tree = load_tree()

    # Load synapses if not provided
    if synapses is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from knowledge_synapses import load_synapses
        synapses = load_synapses()

    # Find the target leaf
    branch_name, leaf = _find_leaf(tree, leaf_id)
    if leaf is None:
        return {
            "leaf_id": leaf_id,
            "content": "",
            "branch": "",
            "base_confidence": 0.0,
            "net_confidence": 0.0,
            "stance": "NOT_FOUND",
            "reasoning": f"Leaf '{leaf_id}' not found in the knowledge tree.",
            "support_count": 0,
            "contradiction_count": 0,
            "superseded": False,
            "depth_reached": 0,
        }

    base_confidence = leaf["confidence"]

    # Check for SUPERSEDES edges pointing TO this leaf
    all_synapses = synapses.get("synapses", [])
    superseded = any(
        s["relation"] == "SUPERSEDES" and s["to_leaf"] == leaf_id
        for s in all_synapses
    )

    if superseded:
        return {
            "leaf_id": leaf_id,
            "content": leaf["content"][:80],
            "branch": branch_name,
            "base_confidence": base_confidence,
            "net_confidence": base_confidence,
            "stance": "SUPERSEDED",
            "reasoning": "This belief has been superseded. Treating as stale regardless of confidence.",
            "support_count": 0,
            "contradiction_count": 0,
            "superseded": True,
            "depth_reached": 0,
        }

    # BFS traversal to collect support/contradiction effects
    support_effect = 0.0
    contradiction_effect = 0.0
    support_count = 0
    contradiction_count = 0
    max_depth_reached = 0

    visited = {leaf_id}
    # Queue: (neighbor_leaf_id, relation, direction, depth)
    # direction: "outgoing" if edge goes FROM leaf_id, "incoming" if TO leaf_id
    queue = []

    # Seed queue with direct neighbors
    for s in _get_synapses_for_leaf(synapses, leaf_id):
        if s["from_leaf"] == leaf_id:
            neighbor_id = s["to_leaf"]
        else:
            neighbor_id = s["from_leaf"]
        if neighbor_id not in visited:
            queue.append((neighbor_id, s["relation"], 1))

    while queue:
        neighbor_id, relation, depth = queue.pop(0)

        if depth > max_depth:
            continue
        if neighbor_id in visited:
            continue
        visited.add(neighbor_id)

        if depth > max_depth_reached:
            max_depth_reached = depth

        # Find the neighbor leaf to get its confidence
        _, neighbor_leaf = _find_leaf(tree, neighbor_id)
        if neighbor_leaf is None:
            continue

        neighbor_conf = neighbor_leaf["confidence"]
        decay = DEPTH_DECAY ** (depth - 1)

        # Determine relation weight multiplier
        relation_mult = WEAK_MULTIPLIER if relation in WEAK_RELATIONS else 1.0

        if relation in ("SUPPORTS", "REFINES", "DERIVES_FROM"):
            support_effect += neighbor_conf * SUPPORT_WEIGHT * decay * relation_mult
            support_count += 1
        elif relation == "CONTRADICTS":
            contradiction_effect += neighbor_conf * CONTRADICTION_WEIGHT * decay * relation_mult
            contradiction_count += 1
        # SUPERSEDES edges on neighbors don't affect this leaf's score (already handled above)

        # Enqueue neighbors of this neighbor (depth + 1)
        if depth < max_depth:
            for s in _get_synapses_for_leaf(synapses, neighbor_id):
                if s["from_leaf"] == neighbor_id:
                    next_id = s["to_leaf"]
                else:
                    next_id = s["from_leaf"]
                if next_id not in visited:
                    queue.append((next_id, s["relation"], depth + 1))

    # Compute net confidence
    net = base_confidence + support_effect - contradiction_effect
    net = max(0.0, min(1.0, net))

    # Determine stance
    if contradiction_count > 0 and net < 0.7:
        stance = "CONTESTED"
    elif net < 0.7:
        stance = "UNCERTAIN"
    else:
        stance = "CONFIDENT"

    # Build reasoning string
    if support_count == 0 and contradiction_count == 0:
        reasoning = (
            f"No supporting or contradicting evidence in the graph. "
            f"Base confidence: {base_confidence:.2f} — {stance}."
        )
    else:
        parts = [f"I hold this at base {base_confidence:.2f}"]
        if support_count > 0:
            parts.append(
                f"supported by {support_count} {'leaf' if support_count == 1 else 'leaves'} "
                f"(net effect +{support_effect:.2f})"
            )
        if contradiction_count > 0:
            parts.append(
                f"contradicted by {contradiction_count} "
                f"{'leaf' if contradiction_count == 1 else 'leaves'} "
                f"(net effect -{contradiction_effect:.2f})"
            )
        if support_count == 0:
            parts.append("no supporting evidence")
        if contradiction_count == 0:
            parts.append("no contradictions")
        reasoning = ", ".join(parts) + f". Net belief: {net:.2f} — {stance}."

    return {
        "leaf_id": leaf_id,
        "content": leaf["content"][:80],
        "branch": branch_name,
        "base_confidence": base_confidence,
        "net_confidence": round(net, 10),  # avoid float artifacts
        "stance": stance,
        "reasoning": reasoning,
        "support_count": support_count,
        "contradiction_count": contradiction_count,
        "superseded": False,
        "depth_reached": max_depth_reached,
    }
