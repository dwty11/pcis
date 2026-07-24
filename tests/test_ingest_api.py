#!/usr/bin/env python3
"""Entry-point tests for POST /api/ingest.

Regression guard for a cold-read finding: when Ollama is down, /api/search
degrades gracefully (keyword fallback) but /api/ingest returned a raw HTTP 500
with the bare "<urlopen error [Errno 61] Connection refused>" string printed to
the page. Ingestion genuinely needs the LLM to extract claims, so it can't fall
back — but it must fail *cleanly and actionably*, not dump a stack string.

The outage is driven the REAL way — the claim extractor is pointed at a
definitely-closed port, so the actual urllib call raises the actual URLError the
production path sees. No mock stands in for the network error.
"""
import json
import os
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(TESTS_DIR, "..")
sys.path.insert(0, ROOT_DIR)

os.environ.setdefault("PCIS_BASE_DIR", tempfile.mkdtemp())

from demo.server import app


def _closed_port_url():
    """A URL on a port guaranteed to refuse — bind then release it."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/v1"


class TestIngestAPI(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_ingest_degrades_gracefully_when_llm_unreachable(self):
        dead = _closed_port_url()
        with patch("core.doc_ingest.LLM_BASE_URL", dead):
            resp = self.client.post(
                "/api/ingest",
                data=json.dumps({"content": "Meridian Corp finalized its AI usage policy in 2026."}),
                content_type="application/json",
            )

        # Graceful, like /api/search — not a raw 500 internal error.
        self.assertEqual(
            resp.status_code, 503,
            f"expected 503 (dependency unavailable), got {resp.status_code}",
        )
        body = resp.get_json()
        # The raw urllib/stack string must never reach the user.
        self.assertNotIn("urlopen", json.dumps(body).lower())
        self.assertNotIn("errno", json.dumps(body).lower())
        # A clean, actionable signal the local LLM is what's missing.
        self.assertTrue(body.get("ollama_unavailable"), f"missing ollama_unavailable flag: {body}")
        self.assertIn("ollama", body.get("error", "").lower())

    def test_ingest_empty_content_still_400(self):
        # Guard: the new branch must not swallow the existing empty-content path.
        resp = self.client.post(
            "/api/ingest",
            data=json.dumps({"content": "   "}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
