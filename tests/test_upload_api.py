"""Tests for /api/ingest/upload endpoint."""

import io
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from demo.server import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_upload_txt_returns_extracted_text(client):
    """Upload a .txt file and verify extracted text is returned."""
    content = "PCI DSS requires encryption of cardholder data at rest."
    data = {"file": (io.BytesIO(content.encode()), "policy.txt")}
    resp = client.post(
        "/api/ingest/upload", data=data, content_type="multipart/form-data"
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["text"] == content
    assert body["filename"] == "policy.txt"
    assert body["chars"] == len(content)


def test_upload_no_file_returns_400(client):
    """POST without a file field returns 400."""
    resp = client.post("/api/ingest/upload", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "No file" in resp.get_json()["error"]


def test_upload_unsupported_extension_returns_400(client):
    """Upload a .csv file returns 400 unsupported type."""
    data = {"file": (io.BytesIO(b"a,b,c"), "data.csv")}
    resp = client.post(
        "/api/ingest/upload", data=data, content_type="multipart/form-data"
    )
    assert resp.status_code == 400
    assert "Unsupported" in resp.get_json()["error"]
