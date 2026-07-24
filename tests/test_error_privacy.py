#!/usr/bin/env python3
"""Privacy guard: a generic 500 must never surface the raw exception string.

An OSError deep in a handler (e.g. a permission-denied write) stringifies to
something like "[Errno 13] Permission denied: '<abs>/private/file.json'" — an
absolute path that leaks the operator's username and directory structure to
anyone hitting the endpoint. Same class as the pre-push leak guard catching a
username echoed into a commit. These endpoints must log the detail server-side
and return a fixed, friendly message.

Entry-point tests: they POST to the real Flask endpoints and force the failure
the exact way production would raise it.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(TESTS_DIR, "..")
sys.path.insert(0, ROOT_DIR)

os.environ.setdefault("PCIS_BASE_DIR", tempfile.mkdtemp())

from demo.server import app

SECRET_PATH = "/opt/example-operator/workspace/synapses.json"


def _assert_no_leak(test, resp):
    test.assertEqual(resp.status_code, 500)
    blob = json.dumps(resp.get_json())
    test.assertNotIn(SECRET_PATH, blob)
    test.assertNotIn("example-operator", blob)
    test.assertNotIn("Permission denied", blob)
    test.assertNotIn("Errno", blob)


class TestErrorPrivacy(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_belief_recompute_500_hides_internal_error(self):
        err = OSError(13, "Permission denied", SECRET_PATH)
        with patch("core.belief_updater.recompute_all", side_effect=err):
            resp = self.client.post("/api/belief/recompute")
        _assert_no_leak(self, resp)

    def test_ingest_upload_500_hides_internal_error(self):
        err = OSError(13, "Permission denied", SECRET_PATH)
        with patch("core.doc_ingest._read_pdf", side_effect=err):
            resp = self.client.post(
                "/api/ingest/upload",
                data={"file": (io.BytesIO(b"%PDF-1.4 fake"), "x.pdf")},
                content_type="multipart/form-data",
            )
        _assert_no_leak(self, resp)

    def test_ingest_500_hides_internal_error(self):
        # Regression guard for the generic branch already hardened in 657125e:
        # a non-URLError failure must not leak str(e) either.
        err = ValueError(f"parse blew up at {SECRET_PATH}")
        with patch("core.doc_ingest.extract_claims_from_text", side_effect=err):
            resp = self.client.post(
                "/api/ingest",
                data=json.dumps({"content": "Meridian Corp shipped a policy in 2026."}),
                content_type="application/json",
            )
        _assert_no_leak(self, resp)


if __name__ == "__main__":
    unittest.main()
