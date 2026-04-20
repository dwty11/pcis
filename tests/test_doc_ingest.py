#!/usr/bin/env python3
"""
Tests for document ingestion pipeline.
Run: python3 tests/test_doc_ingest.py
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
sys.path.insert(0, os.path.join(ROOT_DIR, "core"))
sys.path.insert(0, ROOT_DIR)

# Use a temp dir so tests don't touch real data
_tmp_base = tempfile.mkdtemp()
os.environ["PCIS_BASE_DIR"] = _tmp_base
os.makedirs(os.path.join(_tmp_base, "data"), exist_ok=True)

import knowledge_tree as kt
from core.doc_ingest import (
    extract_claims_from_text,
    ingest_document,
    read_document,
    read_markdown,
    split_markdown_by_headers,
    _extract_text_from_pdf_binary,
    INGEST_BRANCH,
    DEFAULT_CONFIDENCE,
)


def _mock_llm_response(claims):
    """Build a fake urllib response that returns a JSON array of claims."""
    response_body = json.dumps({
        "choices": [{
            "message": {
                "content": json.dumps(claims),
            }
        }]
    }).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


class TestExtractClaims(unittest.TestCase):
    """Test LLM claim extraction with mocked HTTP calls."""

    def test_extracts_claims_from_paragraph(self):
        """A short paragraph yields the expected claims."""
        fake_claims = [
            "Passwords must be at least 14 characters.",
            "MFA is required for admin accounts.",
            "Access reviews happen quarterly.",
        ]

        with patch("urllib.request.urlopen", return_value=_mock_llm_response(fake_claims)):
            result = extract_claims_from_text("Some policy document text here.")

        self.assertEqual(result, fake_claims)

    def test_handles_markdown_fenced_response(self):
        """LLM response wrapped in ```json ... ``` is parsed correctly."""
        claims = ["Claim one.", "Claim two."]
        fenced = "```json\n" + json.dumps(claims) + "\n```"

        response_body = json.dumps({
            "choices": [{"message": {"content": fenced}}]
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = extract_claims_from_text("Test content.")

        self.assertEqual(result, claims)

    def test_empty_claims_filtered(self):
        """Empty strings in the LLM response are filtered out."""
        claims_with_empty = ["Valid claim.", "", "  ", "Another claim."]

        with patch("urllib.request.urlopen", return_value=_mock_llm_response(claims_with_empty)):
            result = extract_claims_from_text("Test.")

        self.assertEqual(result, ["Valid claim.", "Another claim."])


class TestIngestDocument(unittest.TestCase):
    """Test leaf creation and tree commit."""

    def _empty_tree(self):
        return {
            "version": 1, "instance": "test", "root_hash": "",
            "last_updated": "2026-01-01 00:00:00 UTC",
            "branches": {},
        }

    def test_leaves_committed_to_tree(self):
        """Ingested claims become leaves in the 'ingested' branch."""
        fake_claims = [
            "All data must be encrypted at rest.",
            "Backups are retained for 7 years.",
            "Incident response within 1 hour.",
        ]

        tree = self._empty_tree()

        with patch("core.doc_ingest.extract_claims_from_text", return_value=fake_claims):
            result = ingest_document("doc text", source="test-policy.txt", tree=tree, save=False)

        self.assertEqual(result["count"], 3)
        self.assertEqual(result["source"], "test-policy.txt")
        self.assertEqual(len(result["leaves"]), 3)

        # Verify leaves are in the tree
        self.assertIn(INGEST_BRANCH, tree["branches"])
        branch_leaves = tree["branches"][INGEST_BRANCH]["leaves"]
        self.assertEqual(len(branch_leaves), 3)

        for leaf in branch_leaves:
            self.assertEqual(leaf["confidence"], DEFAULT_CONFIDENCE)
            self.assertEqual(leaf["source"], "test-policy.txt")

    def test_root_hash_changes_after_ingest(self):
        """Tree root hash changes after ingestion — Merkle integrity holds."""
        tree = self._empty_tree()
        root_before = kt.compute_root_hash(tree)

        with patch("core.doc_ingest.extract_claims_from_text", return_value=["A fact."]):
            result = ingest_document("doc", tree=tree, save=False)

        self.assertNotEqual(result["root_hash"], root_before)

    def test_multiple_ingestions_accumulate(self):
        """Multiple ingestions add to the same branch, not overwrite."""
        tree = self._empty_tree()

        with patch("core.doc_ingest.extract_claims_from_text", return_value=["Fact A."]):
            ingest_document("doc1", tree=tree, save=False)

        with patch("core.doc_ingest.extract_claims_from_text", return_value=["Fact B.", "Fact C."]):
            ingest_document("doc2", tree=tree, save=False)

        self.assertEqual(len(tree["branches"][INGEST_BRANCH]["leaves"]), 3)

    def test_tree_integrity_after_ingest(self):
        """The tree passes integrity verification after ingestion."""
        tree = self._empty_tree()

        with patch("core.doc_ingest.extract_claims_from_text", return_value=["Claim 1.", "Claim 2."]):
            ingest_document("doc", tree=tree, save=False)

        # Finalize hashes (normally done by save_tree)
        for bname in tree["branches"]:
            tree["branches"][bname]["hash"] = kt.compute_branch_hash(
                tree["branches"][bname]["leaves"]
            )
        tree["root_hash"] = kt.compute_root_hash(tree)

        ok, errors = kt.verify_tree_integrity(tree)
        self.assertTrue(ok, f"Tree integrity check failed: {errors}")


class TestReadDocument(unittest.TestCase):
    """Test file reading."""

    def test_read_text_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Hello, world!")
            f.flush()
            path = f.name

        try:
            content = read_document(path)
            self.assertEqual(content, "Hello, world!")
        finally:
            os.unlink(path)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            read_document("/nonexistent/file.txt")


class TestMarkdownIngestion(unittest.TestCase):
    """Test markdown splitting and ingestion."""

    def test_split_by_headers(self):
        """Markdown is split into chunks at each header."""
        md = (
            "Some intro text.\n"
            "\n"
            "# First Section\n"
            "Content of first section.\n"
            "\n"
            "## Subsection\n"
            "Subsection content.\n"
            "\n"
            "# Second Section\n"
            "Content of second section.\n"
        )
        chunks = split_markdown_by_headers(md)
        self.assertEqual(len(chunks), 4)
        self.assertEqual(chunks[0]["heading"], "Introduction")
        self.assertIn("intro text", chunks[0]["content"])
        self.assertEqual(chunks[1]["heading"], "First Section")
        self.assertEqual(chunks[1]["level"], 1)
        self.assertEqual(chunks[2]["heading"], "Subsection")
        self.assertEqual(chunks[2]["level"], 2)
        self.assertEqual(chunks[3]["heading"], "Second Section")

    def test_no_headers_single_chunk(self):
        """Markdown with no headers becomes one 'Introduction' chunk."""
        md = "Just a paragraph.\n\nAnother paragraph."
        chunks = split_markdown_by_headers(md)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["heading"], "Introduction")

    def test_empty_sections_skipped(self):
        """Empty sections (header with no content) are not included."""
        md = "# A\n# B\nContent for B."
        chunks = split_markdown_by_headers(md)
        # "A" has no content between it and "B", so only "B" has content
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["heading"], "B")

    def test_read_markdown_file(self):
        """read_markdown reads a .md file and returns chunks."""
        md_content = "# Title\nHello world.\n\n## Sub\nDetails here."
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(md_content)
            f.flush()
            path = f.name
        try:
            chunks = read_markdown(path)
            self.assertEqual(len(chunks), 2)
            self.assertEqual(chunks[0]["heading"], "Title")
            self.assertEqual(chunks[1]["heading"], "Sub")
        finally:
            os.unlink(path)

    def test_read_markdown_missing_file(self):
        """read_markdown raises FileNotFoundError for missing file."""
        with self.assertRaises(FileNotFoundError):
            read_markdown("/nonexistent/file.md")


class TestPDFIngestion(unittest.TestCase):
    """Test PDF text extraction fallback."""

    def test_binary_extraction_finds_text(self):
        """The binary fallback extracts readable strings from a fake PDF."""
        # Create a minimal file with some embedded text
        content = b"%PDF-1.4\nsome binary junk\x00\x01\x02"
        content += b"This is the real content of the document"
        content += b"\x00more junk\x01\x02"
        content += b"Another meaningful sentence here for testing"
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(content)
            f.flush()
            path = f.name
        try:
            text = _extract_text_from_pdf_binary(path)
            self.assertIn("real content", text)
            self.assertIn("meaningful sentence", text)
        finally:
            os.unlink(path)

    def test_binary_extraction_raises_on_empty(self):
        """Binary extraction raises RuntimeError when no text found."""
        # A file with only non-printable bytes
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"\x00\x01\x02\x03" * 100)
            f.flush()
            path = f.name
        try:
            with self.assertRaises(RuntimeError):
                _extract_text_from_pdf_binary(path)
        finally:
            os.unlink(path)

    def test_read_document_pdf_with_pdftotext_fallback(self):
        """read_document for PDF falls through to binary extraction."""
        content = b"%PDF-1.4\n"
        content += b"Extractable text from a PDF file for testing"
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(content)
            f.flush()
            path = f.name
        try:
            # This will try pdftotext (may not be installed), then binary fallback
            text = read_document(path)
            self.assertTrue(len(text) > 0)
        finally:
            os.unlink(path)


class TestIngestAPI(unittest.TestCase):
    """Test the /api/ingest endpoint."""

    def setUp(self):
        sys.path.insert(0, os.path.join(ROOT_DIR, "demo"))
        # Create a temporary demo tree for the server
        self._tmp_dir = tempfile.mkdtemp()
        self._demo_tree_path = os.path.join(self._tmp_dir, "demo_tree.json")
        demo_tree = {
            "version": 1, "instance": "test", "root_hash": "",
            "last_updated": "2026-01-01 00:00:00 UTC",
            "branches": {
                "identity": {"hash": kt.compute_branch_hash([]), "leaves": []},
            },
        }
        demo_tree["root_hash"] = kt.compute_root_hash(demo_tree)
        with open(self._demo_tree_path, "w") as f:
            json.dump(demo_tree, f)

        # Patch the demo server to use our temp tree
        import demo.server as srv
        self._orig_tree_file = srv.DEMO_TREE_FILE
        srv.DEMO_TREE_FILE = self._demo_tree_path
        self.app = srv.app.test_client()

    def tearDown(self):
        import demo.server as srv
        srv.DEMO_TREE_FILE = self._orig_tree_file
        shutil.rmtree(self._tmp_dir)

    def test_empty_content_returns_400(self):
        resp = self.app.post("/api/ingest",
                             json={"content": "", "source": "test"})
        self.assertEqual(resp.status_code, 400)

    def test_successful_ingest(self):
        fake_claims = ["Fact 1.", "Fact 2."]

        with patch("core.doc_ingest.extract_claims_from_text", return_value=fake_claims):
            resp = self.app.post("/api/ingest",
                                 json={"content": "A document.", "source": "test-doc"})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["source"], "test-doc")
        self.assertEqual(len(data["leaves"]), 2)
        self.assertIn("root_hash", data)
        self.assertTrue(len(data["root_hash"]) == 64)


if __name__ == "__main__":
    print("PCIS Document Ingestion Tests\n" + "=" * 40)
    unittest.main(verbosity=2)
