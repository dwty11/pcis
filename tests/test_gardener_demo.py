"""Tests for the offline gardener demo + the reseeded demo tree (P3).

Red-first:
  - run_demo must move the Merkle root with NO Ollama/LLM call (offline).
  - run_demo (default) must NOT mutate the shipped demo tree.
  - the shipped demo tree must ship readable, hand-authored synthetic COUNTER
    leaves that reference real demo leaves and keep the tree internally consistent.
"""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "core"))
# gardener.py hard-exits at import if PCIS_BASE_DIR is unset — set a throwaway.
os.environ.setdefault("PCIS_BASE_DIR", tempfile.mkdtemp())

import gardener  # noqa: E402
from knowledge_tree import verify_tree_integrity  # noqa: E402

DEMO_TREE = REPO_ROOT / "demo" / "demo_tree.json"


def _no_llm(monkeypatch):
    monkeypatch.setattr(gardener, "ensure_ollama_warm",
                        lambda *a, **k: pytest.fail("ensure_ollama_warm called in --demo (must be offline)"))
    monkeypatch.setattr(gardener, "call_llm",
                        lambda *a, **k: pytest.fail("call_llm called in --demo (must be offline)"))


def test_run_demo_moves_root_offline(monkeypatch, tmp_path):
    _no_llm(monkeypatch)
    seed = tmp_path / "tree.json"
    seed.write_text(DEMO_TREE.read_text())
    counters = [{
        "branch": "risks",
        "content": "COUNTER: [a2b92e85661a] synthetic offline-demo challenge — pure fiction.",
        "confidence": 0.6,
    }]
    result = gardener.run_demo(seed_path=str(seed), counters=counters)
    assert result["counters_added"] >= 1
    assert result["root_before"] != result["root_after"]


def test_run_demo_does_not_mutate_shipped_tree(monkeypatch):
    _no_llm(monkeypatch)
    before = hashlib.sha256(DEMO_TREE.read_bytes()).hexdigest()
    gardener.run_demo()  # default: reads shipped tree, no out_path -> must not write
    after = hashlib.sha256(DEMO_TREE.read_bytes()).hexdigest()
    assert before == after


def test_demo_tree_ships_readable_counters():
    tree = json.loads(DEMO_TREE.read_text())
    all_leaves = [(bn, l) for bn, b in tree["branches"].items() for l in b["leaves"]]
    all_ids = {l["id"] for _, l in all_leaves}
    counters = [(bn, l) for bn, l in all_leaves if l["content"].startswith("COUNTER:")]
    assert len(counters) >= 3, f"demo tree must ship readable COUNTER leaves, found {len(counters)}"
    for _, c in counters:
        # Each counter names a real challenged leaf id (for /api/adversarial cross-ref).
        assert "[" in c["content"] and "]" in c["content"], c["content"]
        challenged = c["content"][c["content"].index("[") + 1:c["content"].index("]")]
        assert challenged in all_ids, f"counter challenges unknown id {challenged}"
    ok, errors = verify_tree_integrity(tree)
    assert ok, f"reseeded demo tree fails integrity: {errors}"
