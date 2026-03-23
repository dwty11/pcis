"""
PCIS — Persistent Cognitive Identity Systems.

    from pcis import load_tree, add_knowledge, prune_leaf, compute_root_hash, tree_lock, search
"""
import sys
import os

# Allow imports from the repo root so core.* resolves
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from core.knowledge_tree import (
    load_tree,
    save_tree,
    add_knowledge,
    prune_leaf,
    compute_root_hash,
    tree_lock,
)
from core.knowledge_search import search

__all__ = [
    "load_tree",
    "save_tree",
    "add_knowledge",
    "prune_leaf",
    "compute_root_hash",
    "tree_lock",
    "search",
]
