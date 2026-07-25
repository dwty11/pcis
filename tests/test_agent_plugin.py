"""test_agent_plugin.py — coverage for the agent-plugin tool surface.

WHY THIS FILE EXISTS
====================
``agent-plugin/`` shipped with ZERO test coverage. As a result
``pcis_search`` was broken from the start in two stacked ways and nobody
noticed, while ``agent-plugin/README.md`` documented it as working:

  1. ``core.knowledge_search.search`` yields 3-tuples
     ``(score, leaf_id, leaf_data)`` (core/knowledge_search.py:307), but
     the plugin unpacked two — ``ValueError: too many values to unpack``.
  2. Behind that, it read ``leaf["id"]`` — a key search-index entries do
     not carry (the id is the *dict key*, and the second tuple element).

NON-VACUOUS BY CONSTRUCTION
===========================
``search()`` returns ``[]`` and prints "Search index is empty" when no
index exists (core/knowledge_search.py:290-292). On that path the plugin
never unpacks anything, so a test that forgets to build an index passes
while proving nothing — which is exactly how the bug survived.

So these tests build a REAL on-disk search index and let the REAL
``search()`` run. Only ``get_embedding`` is stubbed, because it is the
one genuine external dependency (an Ollama HTTP call). The tuple arity,
the index lookup, and the plugin's unpacking are all exercised for real.
``test_search_yields_three_tuples`` pins the arity directly so a future
change to ``search()`` reds here instead of silently re-breaking callers.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, _ROOT)

PLUGIN_PY = os.path.join(_ROOT, "agent-plugin", "plugin.py")

# A leaf that will be retrievable through the real search path.
LEAF_CONTENT = "PCIS records which leaves were injected into a prompt"
LEAF_BRANCH = "technical"
VECTOR = [0.5, 0.25, 0.125, 0.0625]


def _load_plugin():
    """Import agent-plugin/plugin.py by path — the directory name has a
    hyphen, so it is not importable as a package."""
    spec = importlib.util.spec_from_file_location("pcis_agent_plugin", PLUGIN_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def plugin_env(tmp_path, monkeypatch):
    """A real tree + a real search index under PCIS_BASE_DIR=tmp_path.

    Returns (plugin_module, config, leaf_id).
    """
    monkeypatch.setenv("PCIS_BASE_DIR", str(tmp_path))
    data = tmp_path / "data"
    data.mkdir()

    import knowledge_tree as kt

    tree = {"branches": {}, "root_hash": ""}
    leaf_id = kt.add_knowledge(
        tree, LEAF_BRANCH, LEAF_CONTENT, source="test", confidence=0.8
    )
    kt.save_tree(tree, str(data / "tree.json"))

    # Rebuild the index shape that reindex() writes (core/knowledge_search.py:223-230).
    saved = kt.load_tree(str(data / "tree.json"))
    leaf = saved["branches"][LEAF_BRANCH]["leaves"][0]
    index = {
        "model": "nomic-embed-text",
        "dimensions": len(VECTOR),
        "created": leaf["created"],
        "last_reindex": leaf["created"],
        "leaf_count": 1,
        "embeddings": {
            leaf_id: {
                "branch": LEAF_BRANCH,
                "content": leaf["content"],
                "source": leaf["source"],
                "confidence": leaf["confidence"],
                "created": leaf["created"],
                "vector": list(VECTOR),
            }
        },
    }
    index_path = data / "search-index.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")

    import knowledge_search as ks
    import core.knowledge_search as core_ks
    import core.knowledge_tree as core_kt

    # BASE_DIR / TREE_FILE / INDEX_FILE are captured at IMPORT time, so
    # monkeypatch.setenv alone leaves them pinned to whichever tmp dir
    # imported the module first — leaves then accumulate across tests.
    # Repoint every module alias explicitly (the idiom demo/server.py:53-54 uses).
    for mod in (ks, core_ks):
        monkeypatch.setattr(mod, "INDEX_FILE", str(index_path))
        monkeypatch.setattr(mod, "TREE_FILE", str(data / "tree.json"))
        # Stub ONLY the Ollama call. Query embeds to the stored vector, so
        # cosine similarity is 1.0 and the leaf clears min_score.
        monkeypatch.setattr(mod, "get_embedding", lambda text, model=None: list(VECTOR))
    for mod in (kt, core_kt):
        monkeypatch.setattr(mod, "BASE_DIR", str(tmp_path))
        monkeypatch.setattr(mod, "TREE_FILE", str(data / "tree.json"))

    return _load_plugin(), {"base_dir": str(tmp_path)}, leaf_id


def test_search_yields_three_tuples(plugin_env):
    """Pin search()'s return arity — the contract the plugin got wrong."""
    _plugin, _config, leaf_id = plugin_env
    from core.knowledge_search import search

    results = search("injected into a prompt", top_k=5)

    assert results, (
        "search() returned no results, so this fixture proves nothing. "
        "The index or the embedding stub is misconfigured."
    )
    for row in results:
        assert len(row) == 3, f"expected (score, leaf_id, leaf_data), got {len(row)}-tuple"
    scores, ids, datas = zip(*results)
    assert leaf_id in ids
    assert all(isinstance(d, dict) for d in datas)
    assert "id" not in datas[0], (
        "search-index entries must NOT carry an 'id' key — the leaf id is the "
        "dict key. A caller reading leaf['id'] is the bug this file guards."
    )


def test_pcis_search_returns_the_retrieved_leaf(plugin_env):
    """The core regression: pcis_search must survive real search() output."""
    plugin, config, leaf_id = plugin_env

    results = plugin.pcis_search("injected into a prompt", config=config)

    assert results, "pcis_search returned nothing over a populated index"
    assert [r["leaf_id"] for r in results] == [leaf_id]


def test_pcis_search_result_shape(plugin_env):
    """The documented return shape (agent-plugin/README.md:49)."""
    plugin, config, leaf_id = plugin_env

    row = plugin.pcis_search("injected into a prompt", config=config)[0]

    assert set(row) == {"score", "leaf_id", "branch", "content", "confidence"}
    assert row["branch"] == LEAF_BRANCH
    assert row["content"] == LEAF_CONTENT
    assert row["confidence"] == 0.8
    assert 0.0 <= row["score"] <= 1.0


def test_pcis_search_honours_top_k(plugin_env):
    plugin, config, _leaf_id = plugin_env

    assert len(plugin.pcis_search("injected", top_k=1, config=config)) <= 1


def test_pcis_search_empty_index_returns_empty_list(tmp_path, monkeypatch):
    """The silent-[] path must stay non-raising — but it is NOT evidence
    that unpacking works, which is why every other test here builds an index."""
    monkeypatch.setenv("PCIS_BASE_DIR", str(tmp_path))
    (tmp_path / "data").mkdir()
    import knowledge_search as ks
    import core.knowledge_search as core_ks

    for mod in (ks, core_ks):
        monkeypatch.setattr(mod, "INDEX_FILE", str(tmp_path / "data" / "absent.json"))

    plugin = _load_plugin()
    assert plugin.pcis_search("anything", config={"base_dir": str(tmp_path)}) == []


def test_pcis_add_returns_leaf_id_branch_and_root(plugin_env):
    plugin, config, _leaf_id = plugin_env

    out = plugin.pcis_add("lessons", "a lesson worth keeping", config=config)

    assert set(out) == {"leaf_id", "branch", "root_hash"}
    assert out["branch"] == "lessons"
    assert len(out["root_hash"]) == 24
    import knowledge_tree as kt
    from knowledge_synapses import find_leaf_in_tree

    branch, leaf = find_leaf_in_tree(kt.load_tree(), out["leaf_id"])
    assert branch == "lessons"
    assert leaf["content"] == "a lesson worth keeping"


def test_pcis_status_counts_leaves_and_reports_clean(plugin_env):
    plugin, config, _leaf_id = plugin_env

    out = plugin.pcis_status(config=config)

    assert out["integrity"] == "clean"
    assert out["leaves"] == 1
    assert out["branch_counts"] == {LEAF_BRANCH: 1}


def test_on_session_start_reports_clean_integrity(plugin_env):
    plugin, config, _leaf_id = plugin_env

    out = plugin.on_session_start(config)

    assert out["integrity"] == "clean"
    assert out["leaves"] == 1
    assert out["base_dir"] == config["base_dir"]
