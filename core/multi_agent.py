#!/usr/bin/env python3
"""
multi_agent.py — Multi-agent support for PCIS.

Allows multiple AI agents to share a single knowledge tree instance.
Each agent is identified by an agent_id and every leaf tracks authorship.

No external dependencies. Python 3.10+.
"""

from datetime import datetime, timezone

from knowledge_tree import add_knowledge, now_utc


def register_agent(tree, agent_id, metadata=None):
    """Register an agent in the tree's agent registry.

    Args:
        tree: The knowledge tree dict.
        agent_id: Unique string identifier for the agent.
        metadata: Optional dict with display_name, description, etc.

    Returns:
        The agent entry dict.
    """
    if not agent_id or not isinstance(agent_id, str):
        raise ValueError("agent_id must be a non-empty string")

    if "agents" not in tree:
        tree["agents"] = {}

    entry = tree["agents"].get(agent_id, {})
    entry["registered"] = entry.get("registered", now_utc())
    entry["last_seen"] = now_utc()

    if metadata:
        for key, value in metadata.items():
            entry[key] = value

    tree["agents"][agent_id] = entry
    return entry


def add_knowledge_as(tree, agent_id, branch, content, source, confidence):
    """Add knowledge to the tree on behalf of a specific agent.

    Wraps add_knowledge() and sets the author field on the new leaf.

    Args:
        tree: The knowledge tree dict.
        agent_id: The agent adding the knowledge.
        branch: Target branch name.
        content: Leaf content text.
        source: Source attribution string.
        confidence: Confidence value (0.0 - 1.0).

    Returns:
        The new leaf's ID string.
    """
    if not agent_id or not isinstance(agent_id, str):
        raise ValueError("agent_id must be a non-empty string")

    # Ensure agent is registered
    if "agents" not in tree or agent_id not in tree.get("agents", {}):
        register_agent(tree, agent_id)

    leaf_id = add_knowledge(tree, branch, content, source=source, confidence=confidence)

    # Find the leaf we just added and set the author field
    for leaf in tree["branches"][branch]["leaves"]:
        if leaf["id"] == leaf_id:
            leaf["author"] = agent_id
            break

    return leaf_id


def get_agent_contributions(tree, agent_id, since=None):
    """Return all leaves authored by a specific agent.

    Args:
        tree: The knowledge tree dict.
        agent_id: The agent to look up.
        since: Optional datetime — only return leaves created after this time.

    Returns:
        List of (branch_name, leaf) tuples.
    """
    results = []

    for branch_name, branch in tree.get("branches", {}).items():
        for leaf in branch.get("leaves", []):
            if leaf.get("author") != agent_id:
                continue

            if since is not None:
                created = datetime.strptime(
                    leaf["created"], "%Y-%m-%d %H:%M:%S UTC"
                ).replace(tzinfo=timezone.utc)
                if created < since:
                    continue

            results.append((branch_name, leaf))

    return results


def list_agents(tree):
    """Return the registered agents dict.

    Returns:
        Dict mapping agent_id -> agent metadata, or empty dict if no agents.
    """
    return dict(tree.get("agents", {}))
