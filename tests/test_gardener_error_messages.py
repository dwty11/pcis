"""call_ollama must tell the truth about WHY it failed.

A 404 from /api/generate means the requested model isn't pulled — Ollama itself is
up. Reporting that as "unreachable" sent a real debugging session chasing
connectivity on a healthy server (the --live demo path, first executed 2026-07-21).
HTTPError must be caught before URLError (it is a subclass), so a missing model
reads as a missing model, and only a genuine connection failure reads as unreachable.
"""
import os
import sys
import tempfile
import urllib.error

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(TESTS_DIR, "..", "core"))
os.environ.setdefault("PCIS_BASE_DIR", tempfile.mkdtemp())
import gardener as gd  # noqa: E402


def test_404_reports_missing_model_not_unreachable(monkeypatch, caplog):
    def raise_404(req, timeout=None):
        raise urllib.error.HTTPError(gd.OLLAMA_URL, 404, "Not Found", {}, None)
    monkeypatch.setattr(gd.urllib.request, "urlopen", raise_404)
    with caplog.at_level("ERROR", logger="pcis.gardener"):
        with pytest.raises(SystemExit):
            gd.call_ollama("prompt", model="qwen3:14b")
    text = caplog.text
    low = text.lower()
    assert "qwen3:14b" in text, "the missing model must be named"
    assert "pull" in low, "must tell the user how to fix it (pull the model)"
    assert "unreachable" not in low, "a 404 on a healthy Ollama is NOT 'unreachable'"


def test_connection_failure_still_reports_unreachable(monkeypatch, caplog):
    def raise_conn(req, timeout=None):
        raise urllib.error.URLError("Connection refused")
    monkeypatch.setattr(gd.urllib.request, "urlopen", raise_conn)
    with caplog.at_level("ERROR", logger="pcis.gardener"):
        with pytest.raises(SystemExit):
            gd.call_ollama("prompt", model="qwen3:14b")
    assert "unreachable" in caplog.text.lower()
