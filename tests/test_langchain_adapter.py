"""Tests for the LangChain PCISMemory adapter.

LangChain is mocked so tests run without it installed.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

# ── Mock langchain before any adapter import ──────────────────────────

_fake_messages: list = []


class _FakeBaseMessage:
    def __init__(self, content: str = ""):
        self.content = content


class _FakeHumanMessage(_FakeBaseMessage):
    type = "human"


class _FakeAIMessage(_FakeBaseMessage):
    type = "ai"


class _FakeChatMessageHistory:
    def __init__(self):
        self.messages: list = _fake_messages

    def add_user_message(self, message: str) -> None:
        self.messages.append(_FakeHumanMessage(message))

    def add_ai_message(self, message: str) -> None:
        self.messages.append(_FakeAIMessage(message))

    def clear(self) -> None:
        self.messages.clear()


class _FakeBaseChatMemory:
    """Minimal stub that mimics BaseChatMemory's constructor and save_context."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            if hasattr(self, k) or not k.startswith("_"):
                setattr(self, k, v)
        self.chat_memory = _FakeChatMessageHistory()

    def save_context(self, inputs, outputs):
        input_str = list(inputs.values())[0] if inputs else ""
        output_str = list(outputs.values())[0] if outputs else ""
        self.chat_memory.add_user_message(str(input_str))
        self.chat_memory.add_ai_message(str(output_str))


def _fake_get_buffer_string(messages, **kwargs):
    return "\n".join(m.content for m in messages)


# Build the fake module tree
_langchain_mod = mock.MagicMock()
_langchain_memory_mod = mock.MagicMock()
_langchain_memory_mod.BaseChatMemory = _FakeBaseChatMemory
_langchain_schema_mod = mock.MagicMock()
_langchain_schema_mod.BaseMessage = _FakeBaseMessage
_langchain_schema_mod.get_buffer_string = _fake_get_buffer_string

sys.modules.setdefault("langchain", _langchain_mod)
sys.modules.setdefault("langchain.memory", _langchain_memory_mod)
sys.modules.setdefault("langchain.schema", _langchain_schema_mod)

# Now safe to import the adapter
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(TESTS_DIR, "..")
ADAPTERS_DIR = os.path.join(ROOT_DIR, "adapters")
sys.path.insert(0, ADAPTERS_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, "core"))

os.environ.setdefault("PCIS_BASE_DIR", tempfile.mkdtemp())

from langchain_memory import PCISMemory, _extract_facts, _relevance_score  # noqa: E402
import knowledge_tree as kt  # noqa: E402


class TestExtractFacts(unittest.TestCase):
    def test_filters_short_sentences(self):
        facts = _extract_facts("Sure! Got it. REST endpoints should use plural nouns always.")
        self.assertEqual(len(facts), 1)
        self.assertIn("REST", facts[0])

    def test_multiple_facts(self):
        text = (
            "Python decorators modify function behaviour at definition time. "
            "Merkle trees provide cryptographic integrity guarantees."
        )
        facts = _extract_facts(text)
        self.assertEqual(len(facts), 2)

    def test_empty_string(self):
        self.assertEqual(_extract_facts(""), [])


class TestRelevanceScore(unittest.TestCase):
    def test_exact_overlap(self):
        score = _relevance_score("REST endpoints should use plural nouns", "REST plural nouns")
        self.assertGreater(score, 0.5)

    def test_no_overlap(self):
        score = _relevance_score("Python decorators rock", "quantum mechanics")
        self.assertEqual(score, 0.0)

    def test_empty_query(self):
        score = _relevance_score("anything", "")
        self.assertEqual(score, 0.0)


class TestPCISMemory(unittest.TestCase):
    def setUp(self):
        _fake_messages.clear()
        self.tmpdir = tempfile.mkdtemp()
        self.tree_path = os.path.join(self.tmpdir, "data", "tree.json")
        os.makedirs(os.path.dirname(self.tree_path), exist_ok=True)
        # Seed an empty tree
        tree = kt.load_tree(self.tree_path)
        kt.save_tree(tree, self.tree_path)

    def test_memory_variables(self):
        mem = PCISMemory(tree_path=self.tree_path)
        self.assertEqual(mem.memory_variables, ["history"])

    def test_save_and_load(self):
        mem = PCISMemory(tree_path=self.tree_path, k=5, min_confidence=0.5)
        mem.save_context(
            {"input": "What are best practices for REST API design?"},
            {"output": "REST endpoints should use plural nouns and proper HTTP verbs always."},
        )
        # There should now be leaves in the conversations branch
        tree = kt.load_tree(self.tree_path)
        self.assertIn("conversations", tree["branches"])
        leaves = tree["branches"]["conversations"]["leaves"]
        self.assertGreater(len(leaves), 0)

        # load_memory_variables should return something
        result = mem.load_memory_variables({"input": "REST design"})
        self.assertIn("history", result)
        self.assertIsInstance(result["history"], str)

    def test_min_confidence_filter(self):
        """Leaves below min_confidence should be excluded."""
        tree = kt.load_tree(self.tree_path)
        kt.add_knowledge(tree, "conversations", "Low confidence fact that should be filtered out definitely", confidence=0.1)
        kt.add_knowledge(tree, "conversations", "High confidence fact about Merkle trees and cryptographic hashing", confidence=0.9)
        kt.save_tree(tree, self.tree_path)

        mem = PCISMemory(tree_path=self.tree_path, k=10, min_confidence=0.5)
        result = mem.load_memory_variables({"input": "anything"})
        self.assertNotIn("Low confidence", result["history"])
        self.assertIn("High confidence", result["history"])

    def test_k_limits_results(self):
        tree = kt.load_tree(self.tree_path)
        for i in range(20):
            kt.add_knowledge(
                tree, "conversations",
                f"Fact number {i} about software architecture patterns and design principles",
                confidence=0.8,
            )
        kt.save_tree(tree, self.tree_path)

        mem = PCISMemory(tree_path=self.tree_path, k=5)
        result = mem.load_memory_variables({})
        lines = [l for l in result["history"].split("\n") if l.strip()]
        self.assertLessEqual(len(lines), 5)

    def test_clear(self):
        mem = PCISMemory(tree_path=self.tree_path)
        mem.save_context({"input": "hello"}, {"output": "world"})
        mem.clear()
        self.assertEqual(len(mem.chat_memory.messages), 0)


if __name__ == "__main__":
    unittest.main()
