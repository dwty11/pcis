"""
LangChain memory adapter for PCIS.

Provides PCISMemory — a drop-in replacement for ConversationBufferMemory
that persists conversation facts as leaves in a PCIS KnowledgeTree.

Requires: pip install langchain  (optional dependency)
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any, Dict, List, Optional

# LangChain is optional — fail gracefully at import time.
try:
    from langchain.memory import BaseChatMemory
    from langchain.schema import BaseMessage, get_buffer_string

    _HAS_LANGCHAIN = True
except ImportError:  # pragma: no cover
    _HAS_LANGCHAIN = False

    # Provide thin stubs so the class can be *defined* without langchain
    # installed.  Instantiation will still raise.
    class _Stub:
        pass

    BaseChatMemory = _Stub  # type: ignore[misc,assignment]

# Allow running from the repo root (tests, scripts).
_CORE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core")
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)

from knowledge_tree import (  # noqa: E402
    add_knowledge,
    load_tree,
    save_tree,
)

# ── Helpers ────────────────────────────────────────────────────────────

_STOP_WORDS = frozenset(
    "a an the is are was were be been being have has had do does did "
    "will would shall should may might can could i you he she it we they "
    "me him her us them my your his its our their this that and but or "
    "not so if in on at to for of with by from".split()
)


def _extract_facts(text: str) -> List[str]:
    """Split a block of text into sentence-level facts.

    Keeps only sentences with at least 4 non-stop words to filter out
    filler like "Sure!" or "Got it.".
    """
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    facts: List[str] = []
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        words = sent.split()
        significant = [w for w in words if w.lower().strip(".,!?;:") not in _STOP_WORDS]
        if len(significant) >= 4:
            facts.append(sent)
    return facts


def _relevance_score(leaf_content: str, query: str) -> float:
    """Cheap keyword-overlap relevance score in [0, 1]."""
    query_words = {w.lower().strip(".,!?;:") for w in query.split()} - _STOP_WORDS
    if not query_words:
        return 0.0
    leaf_words = {w.lower().strip(".,!?;:") for w in leaf_content.split()}
    overlap = query_words & leaf_words
    return len(overlap) / len(query_words)


# ── Main adapter ───────────────────────────────────────────────────────


class PCISMemory(BaseChatMemory):  # type: ignore[misc]
    """LangChain chat memory backed by a PCIS KnowledgeTree.

    Parameters
    ----------
    tree_path : str
        Filesystem path to the tree JSON file.
    k : int
        Number of most-relevant leaves to return as context.
    min_confidence : float
        Ignore leaves below this confidence threshold.
    """

    tree_path: str = ""
    k: int = 10
    min_confidence: float = 0.5
    memory_key: str = "history"
    human_prefix: str = "Human"
    ai_prefix: str = "AI"

    def __init__(self, tree_path: str, k: int = 10, min_confidence: float = 0.5, **kwargs: Any):
        if not _HAS_LANGCHAIN:
            raise ImportError(
                "langchain is required for PCISMemory. Install it with: pip install langchain"
            )
        super().__init__(tree_path=tree_path, k=k, min_confidence=min_confidence, **kwargs)

    # -- BaseChatMemory interface ----------------------------------------

    @property
    def memory_variables(self) -> List[str]:
        """Keys injected into the prompt template."""
        return [self.memory_key]

    def load_memory_variables(self, inputs: Dict[str, Any]) -> Dict[str, str]:
        """Return top-k relevant leaves as a context string."""
        tree = load_tree(self.tree_path)
        query = " ".join(str(v) for v in inputs.values()) if inputs else ""

        all_leaves: List[Dict[str, Any]] = []
        for branch in tree.get("branches", {}).values():
            for leaf in branch.get("leaves", []):
                if leaf.get("confidence", 0) >= self.min_confidence:
                    all_leaves.append(leaf)

        if query:
            scored = [(leaf, _relevance_score(leaf["content"], query)) for leaf in all_leaves]
            scored.sort(key=lambda x: (-x[1], -x[0].get("confidence", 0)))
        else:
            scored = [(leaf, 0.0) for leaf in all_leaves]
            scored.sort(key=lambda x: x[0].get("created", ""), reverse=True)

        top = scored[: self.k]
        lines = [leaf["content"] for leaf, _ in top]
        return {self.memory_key: "\n".join(lines)}

    def save_context(self, inputs: Dict[str, Any], outputs: Dict[str, str]) -> None:
        """Extract facts from the latest turn and persist them as leaves."""
        super().save_context(inputs, outputs)

        combined = ""
        for v in list(inputs.values()) + list(outputs.values()):
            combined += " " + str(v)

        facts = _extract_facts(combined)

        if facts:
            tree = load_tree(self.tree_path)
            for fact in facts:
                add_knowledge(tree, "conversations", fact, source="langchain", confidence=0.8)
            save_tree(tree, self.tree_path)

    def clear(self) -> None:
        """Reset conversation history in the chat buffer."""
        self.chat_memory.clear()
