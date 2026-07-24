#!/usr/bin/env python3
"""Entry-point tests for POST /api/run-validation — the third instance of the
raw-error rough edge a cold read surfaced.

In the demo's default state (Ollama not running) clicking "Run Live Validation"
hit /api/run-validation, which returned 502 with `Cannot reach Ollama:
<urlopen error [Errno 61] Connection refused>` and the client surfaced it as
alert('Live validation error: ' + <that raw string>). Inconsistent with
/api/search (inline banner) and with the /api/ingest fix (503 + friendly
message). This makes it match: friendly, flagged, no raw urllib text, no alert().
"""
import json
import os
import re
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(TESTS_DIR, "..")
sys.path.insert(0, ROOT_DIR)

os.environ.setdefault("PCIS_BASE_DIR", tempfile.mkdtemp())

from demo.server import app

INDEX_HTML = (Path(ROOT_DIR) / "demo" / "index.html").read_text(encoding="utf-8")


class TestRunValidationAPI(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_degrades_gracefully_when_ollama_down(self):
        # Simulate the exact production outage: urlopen raises the URLError a
        # refused connection produces. (The endpoint's Ollama URL is a literal,
        # so patch the socket boundary, not the logic.)
        err = urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))
        with patch("urllib.request.urlopen", side_effect=err):
            resp = self.client.post("/api/run-validation")

        self.assertEqual(
            resp.status_code, 503,
            f"expected 503 (dependency unavailable), got {resp.status_code}",
        )
        body = resp.get_json()
        blob = json.dumps(body).lower()
        self.assertNotIn("urlopen", blob)
        self.assertNotIn("errno", blob)
        self.assertTrue(body.get("ollama_unavailable"), f"missing ollama_unavailable flag: {body}")
        self.assertIn("ollama", body.get("error", "").lower())

    def test_client_renders_inline_banner_not_alert(self):
        # The runLiveValidation() error path must show an inline banner (like the
        # Search screen), never alert() and never a raw urllib string.
        m = re.search(r"async function runLiveValidation\(\)\s*\{.*?\n\}", INDEX_HTML, re.S)
        self.assertIsNotNone(m, "runLiveValidation() not found in index.html")
        body = m.group(0)
        self.assertNotIn("alert(", body, "run-validation error still uses alert(); use an inline banner")
        self.assertIn("gcBanner", body, "run-validation error should render into the inline banner element")


if __name__ == "__main__":
    unittest.main()
