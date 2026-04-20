#!/usr/bin/env python3
"""Tests for the notify_telegram function in gardener.py"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_DIR = os.path.join(TESTS_DIR, "..", "core")
sys.path.insert(0, CORE_DIR)

_tmpdir = tempfile.mkdtemp()
os.environ["PCIS_BASE_DIR"] = _tmpdir
os.makedirs(os.path.join(_tmpdir, "data"), exist_ok=True)
os.makedirs(os.path.join(_tmpdir, "memory"), exist_ok=True)

# gardener.py requires PCIS_BASE_DIR to be set (hard exit otherwise)
# We also need to mock out the knowledge_search import
sys.modules['knowledge_search'] = MagicMock()

import gardener as gd


class TestNotifyTelegram(unittest.TestCase):

    def test_skips_silently_without_bot_token(self):
        """Should return without error when PCIS_TELEGRAM_BOT_TOKEN is missing."""
        env = {"PCIS_TELEGRAM_CHAT_ID": "123"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("PCIS_TELEGRAM_BOT_TOKEN", None)
            # Should not raise
            gd.notify_telegram(n_counters=1, n_synapses=2, n_flags=3)

    def test_skips_silently_without_chat_id(self):
        """Should return without error when PCIS_TELEGRAM_CHAT_ID is missing."""
        env = {"PCIS_TELEGRAM_BOT_TOKEN": "fake-token"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("PCIS_TELEGRAM_CHAT_ID", None)
            gd.notify_telegram(n_counters=1, n_synapses=2, n_flags=3)

    @patch("gardener.urllib.request.urlopen")
    def test_sends_correct_payload(self, mock_urlopen):
        """Should send the correct message format to Telegram API."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        env = {
            "PCIS_TELEGRAM_BOT_TOKEN": "fake-token",
            "PCIS_TELEGRAM_CHAT_ID": "123456",
        }
        with patch.dict(os.environ, env, clear=False):
            gd.notify_telegram(n_counters=5, n_synapses=3, n_flags=2)

        mock_urlopen.assert_called_once()
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        self.assertIn("fake-token", req.full_url)
        body = json.loads(req.data.decode())
        self.assertEqual(body["chat_id"], "123456")
        self.assertIn("5 counters", body["text"])
        self.assertIn("3 synapses", body["text"])
        self.assertIn("2 flags", body["text"])

    @patch("gardener.urllib.request.urlopen")
    def test_handles_network_error_gracefully(self, mock_urlopen):
        """Should not raise on network errors."""
        mock_urlopen.side_effect = Exception("Network error")

        env = {
            "PCIS_TELEGRAM_BOT_TOKEN": "fake-token",
            "PCIS_TELEGRAM_CHAT_ID": "123456",
        }
        with patch.dict(os.environ, env, clear=False):
            # Should not raise
            gd.notify_telegram(n_counters=1, n_synapses=0, n_flags=0)

    def test_default_zero_counts(self):
        """Default arguments should be zero."""
        os.environ.pop("PCIS_TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("PCIS_TELEGRAM_CHAT_ID", None)
        # Just verify it doesn't crash with defaults
        gd.notify_telegram()


if __name__ == "__main__":
    unittest.main()
