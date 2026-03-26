#!/usr/bin/env python3
"""
Tests for the /api/search endpoint in the PCIS demo server.
"""

import json
import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import patch, MagicMock

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(TESTS_DIR, "..")
sys.path.insert(0, ROOT_DIR)

# Set PCIS_BASE_DIR before importing anything that reads it.
os.environ.setdefault("PCIS_BASE_DIR", tempfile.mkdtemp())

from demo.server import app


class TestSearchAPI(unittest.TestCase):
    """Tests for POST /api/search."""

    def setUp(self):
        self.client = app.test_client()

    def test_empty_query_returns_400(self):
        """Empty or missing query returns 400."""
        resp = self.client.post(
            "/api/search",
            data=json.dumps({"query": ""}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("error", data)

    def test_missing_query_returns_400(self):
        """No query field at all returns 400."""
        resp = self.client.post(
            "/api/search",
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_whitespace_only_query_returns_400(self):
        """Whitespace-only query returns 400."""
        resp = self.client.post(
            "/api/search",
            data=json.dumps({"query": "   "}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    @patch("core.knowledge_search.search")
    def test_correct_response_shape(self, mock_search):
        """Response has results list, query, and model fields."""
        mock_search.return_value = [
            (0.87, "leaf-001", {
                "branch": "technical",
                "content": "Test content here",
                "confidence": 0.9,
                "source": "test-source",
            }),
        ]
        resp = self.client.post(
            "/api/search",
            data=json.dumps({"query": "test query", "top": 3}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()

        # Top-level keys
        self.assertIn("results", data)
        self.assertIn("query", data)
        self.assertIn("model", data)
        self.assertEqual(data["query"], "test query")
        self.assertIsInstance(data["results"], list)
        self.assertEqual(len(data["results"]), 1)

        # Result shape
        r = data["results"][0]
        for key in ("id", "content", "branch", "confidence", "score", "source"):
            self.assertIn(key, r, f"Missing key: {key}")
        self.assertEqual(r["id"], "leaf-001")
        self.assertEqual(r["branch"], "technical")
        self.assertAlmostEqual(r["score"], 0.87, places=2)

        # No fallback flag when semantic search works
        self.assertNotIn("fallback", data)

    @patch("core.knowledge_search.search")
    def test_fallback_when_ollama_unavailable(self, mock_search):
        """Falls back to substring match and sets fallback flag."""
        mock_search.side_effect = Exception("Connection refused")

        resp = self.client.post(
            "/api/search",
            data=json.dumps({"query": "identity"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()

        self.assertTrue(data.get("fallback"), "Expected fallback=true when Ollama fails")
        self.assertIn("results", data)
        self.assertIn("query", data)
        self.assertIn("model", data)
        # Results may or may not be empty depending on demo tree content,
        # but the response shape must be correct.
        self.assertIsInstance(data["results"], list)

    @patch("core.knowledge_search.search")
    def test_fallback_on_empty_semantic_results(self, mock_search):
        """Falls back when semantic search returns no results."""
        mock_search.return_value = []

        resp = self.client.post(
            "/api/search",
            data=json.dumps({"query": "identity"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("fallback"))

    @patch("core.knowledge_search.search")
    def test_branch_filter_passed(self, mock_search):
        """Branch filter is forwarded to search()."""
        mock_search.return_value = []

        self.client.post(
            "/api/search",
            data=json.dumps({"query": "test", "branch": "technical"}),
            content_type="application/json",
        )
        # search() was called — check the branch_filter kwarg
        mock_search.assert_called_once()
        _, kwargs = mock_search.call_args
        self.assertEqual(kwargs.get("branch_filter"), "technical")

    @patch("core.knowledge_search.search")
    def test_top_parameter_honored(self, mock_search):
        """top parameter controls top_k."""
        mock_search.return_value = []

        self.client.post(
            "/api/search",
            data=json.dumps({"query": "test", "top": 10}),
            content_type="application/json",
        )
        _, kwargs = mock_search.call_args
        self.assertEqual(kwargs.get("top_k"), 10)


if __name__ == "__main__":
    unittest.main()
