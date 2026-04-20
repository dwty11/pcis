#!/usr/bin/env python3
"""Tests for core/multi_agent.py — multi-agent support."""

import os
import sys
import tempfile

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(TESTS_DIR, "..")
sys.path.insert(0, os.path.join(ROOT_DIR, "core"))
sys.path.insert(0, ROOT_DIR)

# Ensure PCIS_BASE_DIR is set for test isolation
_tmp_base = tempfile.mkdtemp()
os.environ["PCIS_BASE_DIR"] = _tmp_base
os.makedirs(os.path.join(_tmp_base, "data"), exist_ok=True)

from datetime import datetime, timezone, timedelta
from core.multi_agent import (
    register_agent,
    add_knowledge_as,
    get_agent_contributions,
    list_agents,
)
from core.knowledge_tree import compute_root_hash


def _empty_tree():
    return {
        "version": 1,
        "instance": "test",
        "root_hash": "",
        "last_updated": "2026-01-01 00:00:00 UTC",
        "branches": {},
    }


class TestRegisterAgent:
    def test_register_new_agent(self):
        tree = _empty_tree()
        entry = register_agent(tree, "agent-alpha")
        assert "agents" in tree
        assert "agent-alpha" in tree["agents"]
        assert "registered" in entry
        assert "last_seen" in entry

    def test_register_with_metadata(self):
        tree = _empty_tree()
        meta = {"display_name": "Alpha", "description": "Research agent"}
        entry = register_agent(tree, "agent-alpha", metadata=meta)
        assert entry["display_name"] == "Alpha"
        assert entry["description"] == "Research agent"

    def test_reregister_updates_metadata(self):
        tree = _empty_tree()
        register_agent(tree, "agent-alpha", metadata={"display_name": "Old"})
        register_agent(tree, "agent-alpha", metadata={"display_name": "New"})
        assert tree["agents"]["agent-alpha"]["display_name"] == "New"
        # registered timestamp should be preserved
        assert "registered" in tree["agents"]["agent-alpha"]

    def test_invalid_agent_id_raises(self):
        tree = _empty_tree()
        with pytest.raises(ValueError):
            register_agent(tree, "")
        with pytest.raises(ValueError):
            register_agent(tree, None)


class TestAddKnowledgeAs:
    def test_leaf_has_author_field(self):
        tree = _empty_tree()
        leaf_id = add_knowledge_as(
            tree, "agent-beta", "technical",
            "Python 3.10 supports match statements",
            source="docs", confidence=0.9,
        )
        leaves = tree["branches"]["technical"]["leaves"]
        assert len(leaves) == 1
        assert leaves[0]["id"] == leaf_id
        assert leaves[0]["author"] == "agent-beta"

    def test_auto_registers_unknown_agent(self):
        tree = _empty_tree()
        add_knowledge_as(
            tree, "agent-gamma", "lessons",
            "Always test before deploying",
            source="experience", confidence=0.85,
        )
        assert "agent-gamma" in tree.get("agents", {})

    def test_invalid_agent_id_raises(self):
        tree = _empty_tree()
        with pytest.raises(ValueError):
            add_knowledge_as(tree, "", "technical", "content", "src", 0.5)


class TestGetAgentContributions:
    def test_returns_only_agent_leaves(self):
        tree = _empty_tree()
        add_knowledge_as(tree, "agent-A", "technical", "Fact from A", "src", 0.8)
        add_knowledge_as(tree, "agent-B", "technical", "Fact from B", "src", 0.7)
        add_knowledge_as(tree, "agent-A", "lessons", "Lesson from A", "src", 0.9)

        contribs = get_agent_contributions(tree, "agent-A")
        assert len(contribs) == 2
        agents = {leaf["author"] for _, leaf in contribs}
        assert agents == {"agent-A"}

    def test_since_filter(self):
        tree = _empty_tree()
        add_knowledge_as(tree, "agent-A", "technical", "Recent fact", "src", 0.8)

        # Ask for contributions since tomorrow — should return nothing
        future = datetime.now(timezone.utc) + timedelta(days=1)
        contribs = get_agent_contributions(tree, "agent-A", since=future)
        assert len(contribs) == 0

        # Ask for contributions since yesterday — should return the leaf
        past = datetime.now(timezone.utc) - timedelta(days=1)
        contribs = get_agent_contributions(tree, "agent-A", since=past)
        assert len(contribs) == 1

    def test_no_contributions_returns_empty(self):
        tree = _empty_tree()
        contribs = get_agent_contributions(tree, "nonexistent-agent")
        assert contribs == []


class TestListAgents:
    def test_list_agents_empty(self):
        tree = _empty_tree()
        assert list_agents(tree) == {}

    def test_list_agents_after_registration(self):
        tree = _empty_tree()
        register_agent(tree, "agent-A", metadata={"display_name": "A"})
        register_agent(tree, "agent-B", metadata={"display_name": "B"})
        agents = list_agents(tree)
        assert len(agents) == 2
        assert "agent-A" in agents
        assert "agent-B" in agents
        assert agents["agent-A"]["display_name"] == "A"
