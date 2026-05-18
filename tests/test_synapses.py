#!/usr/bin/env python3
"""Tests for knowledge_synapses.py and the --link/--links CLI."""

import json
import os
import subprocess
import sys
import tempfile

import pytest

from core.knowledge_synapses import (
    add_synapse,
    compute_synapses_root,
    get_synapses_for_leaf,
    load_synapses,
    save_synapses,
    verify_synapses,
)
from core.knowledge_tree import add_knowledge, load_tree, save_tree


@pytest.fixture
def tmp_workspace(tmp_path, monkeypatch):
    """Set up isolated workspace with a fresh tree and synapses path."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    tree_file = str(data_dir / "tree.json")
    syn_file = str(data_dir / "synapses.json")
    monkeypatch.setenv("PCIS_BASE_DIR", str(tmp_path))
    # Patch module-level paths
    import core.knowledge_tree as kt
    import core.knowledge_synapses as ks
    monkeypatch.setattr(kt, "TREE_FILE", tree_file)
    monkeypatch.setattr(ks, "TREE_FILE", tree_file)
    monkeypatch.setattr(ks, "SYNAPSES_FILE", syn_file)
    return tmp_path, tree_file, syn_file


def _make_tree_with_leaves(tree_file):
    """Create a tree with two leaves and return their IDs."""
    from core.knowledge_tree import load_tree, save_tree, add_knowledge
    tree = load_tree()
    id_a = add_knowledge(tree, "lessons", "First lesson content here")
    id_b = add_knowledge(tree, "technical", "Second piece of technical knowledge")
    save_tree(tree)
    return tree, id_a, id_b


class TestAddSynapse:
    def test_changes_root_hash(self, tmp_workspace):
        _, tree_file, syn_file = tmp_workspace
        tree, id_a, id_b = _make_tree_with_leaves(tree_file)

        synapses = load_synapses(syn_file)
        root_before = compute_synapses_root(synapses)

        add_synapse(synapses, id_a, id_b, "SUPPORTS", note="test")
        save_synapses(synapses, syn_file)

        root_after = synapses["root_hash"]
        assert root_before != root_after

    def test_invalid_relation_raises(self, tmp_workspace):
        _, _, syn_file = tmp_workspace
        synapses = load_synapses(syn_file)
        with pytest.raises(ValueError, match="Invalid relation"):
            add_synapse(synapses, "a", "b", "INVALID")

    def test_note_length_limit(self, tmp_workspace):
        _, _, syn_file = tmp_workspace
        synapses = load_synapses(syn_file)
        with pytest.raises(ValueError, match="500 characters"):
            add_synapse(synapses, "a", "b", "SUPPORTS", note="x" * 501)


class TestGetSynapses:
    def test_returns_both_directions(self, tmp_workspace):
        _, tree_file, syn_file = tmp_workspace
        tree, id_a, id_b = _make_tree_with_leaves(tree_file)

        synapses = load_synapses(syn_file)
        add_synapse(synapses, id_a, id_b, "SUPPORTS")
        save_synapses(synapses, syn_file)

        # Query from source side
        result_a = get_synapses_for_leaf(synapses, id_a)
        assert len(result_a) == 1
        assert result_a[0]["from_leaf"] == id_a

        # Query from target side
        result_b = get_synapses_for_leaf(synapses, id_b)
        assert len(result_b) == 1
        assert result_b[0]["to_leaf"] == id_b


class TestVerify:
    def test_catches_tampered_hash(self, tmp_workspace):
        _, tree_file, syn_file = tmp_workspace
        tree, id_a, id_b = _make_tree_with_leaves(tree_file)

        synapses = load_synapses(syn_file)
        add_synapse(synapses, id_a, id_b, "SUPPORTS")
        save_synapses(synapses, syn_file)

        # Tamper with a synapse hash
        synapses["synapses"][0]["hash"] = "deadbeef" * 8
        ok, errors = verify_synapses(synapses)
        assert not ok
        assert any("hash mismatch" in e for e in errors)

    def test_valid_synapses_pass(self, tmp_workspace):
        _, tree_file, syn_file = tmp_workspace
        tree, id_a, id_b = _make_tree_with_leaves(tree_file)

        synapses = load_synapses(syn_file)
        add_synapse(synapses, id_a, id_b, "CONTRADICTS")
        save_synapses(synapses, syn_file)

        ok, errors = verify_synapses(synapses)
        assert ok
        assert errors == []


class TestCLI:
    def _run(self, args, workspace):
        env = os.environ.copy()
        env["PCIS_BASE_DIR"] = str(workspace)
        result = subprocess.run(
            [sys.executable, "core/knowledge_tree.py"] + args,
            capture_output=True, text=True, env=env,
            cwd=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."),
        )
        return result

    def test_link_smoke(self, tmp_workspace):
        workspace, tree_file, syn_file = tmp_workspace
        tree, id_a, id_b = _make_tree_with_leaves(tree_file)

        result = self._run(
            ["--link", id_a, id_b, "REFINES", "--note", "test link"],
            workspace,
        )
        assert result.returncode == 0
        assert "Synapse created" in result.stdout
        assert id_a in result.stdout

        # Verify file was written
        with open(syn_file) as f:
            data = json.load(f)
        assert len(data["synapses"]) == 1
        assert data["synapses"][0]["relation"] == "REFINES"

    def test_links_smoke(self, tmp_workspace):
        workspace, tree_file, syn_file = tmp_workspace
        tree, id_a, id_b = _make_tree_with_leaves(tree_file)

        # Create a link first
        self._run(["--link", id_a, id_b, "SUPPORTS"], workspace)

        # Query links
        result = self._run(["--links", id_a], workspace)
        assert result.returncode == 0
        assert "SUPPORTS" in result.stdout
        assert id_b in result.stdout

    def test_link_missing_leaf(self, tmp_workspace):
        workspace, tree_file, _ = tmp_workspace
        _make_tree_with_leaves(tree_file)

        result = self._run(
            ["--link", "nonexistent", "also_fake", "SUPPORTS"],
            workspace,
        )
        assert result.returncode != 0
        assert "not found" in result.stdout
