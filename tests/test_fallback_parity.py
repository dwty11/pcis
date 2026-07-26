"""test_fallback_parity.py — the message promises a fallback; every caller must do it.

core/knowledge_search.py prints "keyword search is used instead" when semantic
search is unavailable. That sentence was true for `pcis search` and false for
`pcis_search`, whose only implementation was in pcis/cli.py — so the agent-facing
boundary returned [] while telling the reader a fallback had happened. An agent
cannot distinguish that from an empty tree.

A claim in one module about another module's behaviour is the same defect as a
caption about a value computed elsewhere: the sentence and the behaviour were in
different files, so nothing kept them together. The fallback now lives beside
the message, in core, and these tests hold every caller to it.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, os.path.join(_ROOT, "agent-plugin"))
sys.path.insert(0, _ROOT)


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    """A tree with no search index — the documented first-run state."""
    import knowledge_tree as kt

    monkeypatch.setenv("PCIS_BASE_DIR", str(tmp_path))
    (tmp_path / "data").mkdir()
    tree = {"branches": {}, "root_hash": ""}
    kt.add_knowledge(tree, "technical",
                     "Postgres connection pooling is handled by pgbouncer.",
                     source="t", confidence=0.9)
    kt.save_tree(tree, str(tmp_path / "data" / "tree.json"))

    # BOTH module identities: core/ is on sys.path, so `knowledge_search` and
    # `core.knowledge_search` are distinct objects with separate globals.
    import core.knowledge_search as core_ks
    import knowledge_search as ks

    for mod in (ks, core_ks):
        monkeypatch.setattr(mod, "TREE_FILE", str(tmp_path / "data" / "tree.json"))
        monkeypatch.setattr(mod, "INDEX_FILE", str(tmp_path / "data" / "no-index.json"))
        monkeypatch.setattr(mod, "search", lambda *a, **k: [])
    return tmp_path


def test_plugin_falls_back_rather_than_returning_empty(seeded, monkeypatch):
    """The Class A case: an agent must not read 'dependency missing' as 'no data'."""
    import core.knowledge_search as core_ks
    import plugin

    monkeypatch.setattr(core_ks, "search", lambda *a, **k: [])

    rows = plugin.pcis_search("postgres")

    assert rows, (
        "the plugin returned no rows while the printed message said keyword "
        "search was used — an agent reads that as an empty tree"
    )
    assert "pgbouncer" in rows[0]["content"]


def test_plugin_fallback_declares_a_tree_source(seeded, monkeypatch):
    """Otherwise search_results= labels it index-sourced and the reader renders
    a verdict the comparison cannot support."""
    import core.knowledge_search as core_ks
    import plugin
    from provenance_ledger import load_ledger

    monkeypatch.setattr(core_ks, "search", lambda *a, **k: [])
    plugin.pcis_search("postgres")

    rec = load_ledger(str(seeded / "data" / "provenance-ledger.jsonl"))[-1]
    assert rec.retrieval.extras["injection_source"] == "tree"
    assert rec.retrieval.extras["retrieval_mode"] == "keyword"


def test_the_fallback_lives_beside_the_message_that_promises_it():
    """Structural: a future caller gets the behaviour by importing it, rather
    than by remembering to reimplement it."""
    import knowledge_search as ks

    assert hasattr(ks, "keyword_search"), (
        "the fallback must live in the module that prints the promise"
    )
    assert callable(ks.keyword_search)


def test_both_callers_use_the_shared_implementation():
    """No caller may carry a private copy — that is how they diverged."""
    cli = open(os.path.join(_ROOT, "pcis", "cli.py"), encoding="utf-8").read()
    plug = open(os.path.join(_ROOT, "agent-plugin", "plugin.py"), encoding="utf-8").read()

    for name, src in (("pcis/cli.py", cli), ("agent-plugin/plugin.py", plug)):
        assert "keyword_search" in src, f"{name} does not use the shared fallback"
        assert "def _keyword_search" not in src, (
            f"{name} carries a private copy of the fallback — the divergence "
            "this test exists to prevent"
        )
