"""
PCIS core — Persistent Cognitive Identity Systems.

Public API surface:

    from pcis.core import (
        load_tree,
        add_knowledge,
        prune_leaf,
        compute_root_hash,
        tree_lock,
        search,
    )
"""

from .knowledge_tree import (
    load_tree,
    save_tree,
    add_knowledge,
    prune_leaf,
    compute_root_hash,
    tree_lock,
)
from .knowledge_search import search

__all__ = [
    "load_tree",
    "save_tree",
    "add_knowledge",
    "prune_leaf",
    "compute_root_hash",
    "tree_lock",
    "search",
]
