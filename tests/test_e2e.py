#!/usr/bin/env python3
"""
End-to-end tests for the PCIS demo server.

Starts the Flask server as a subprocess and exercises every public route.
Run: python3 -m pytest tests/test_e2e.py -v
"""

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "core"))
from knowledge_tree import hash_leaf


# ── Session-scoped backup: restores demo_tree.json no matter what ─────────

@pytest.fixture(scope="session", autouse=True)
def _protect_demo_tree(tmp_path_factory):
    src = REPO_ROOT / "demo" / "demo_tree.json"
    backup = tmp_path_factory.mktemp("backup") / "demo_tree.json"
    shutil.copy2(src, backup)
    yield
    shutil.copy2(backup, src)


# ── Server fixture (function-scoped) ─────────────────────────────────────

def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def base_url(tmp_path):
    port = _free_port()
    stderr_log = tmp_path / "server_stderr.log"

    with open(stderr_log, "w") as err_f:
        proc = subprocess.Popen(
            [
                sys.executable,
                str(REPO_ROOT / "demo" / "server.py"),
                "--host", "127.0.0.1",
                "--port", str(port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=err_f,
            cwd=str(REPO_ROOT),
        )

    url = f"http://127.0.0.1:{port}"

    # Poll until the server is ready (up to 10 s)
    deadline = time.monotonic() + 10
    ready = False
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{url}/api/health", timeout=1)
            if r.status_code == 200:
                ready = True
                break
        except requests.ConnectionError:
            pass
        time.sleep(0.5)

    if not ready:
        proc.kill()
        proc.wait()
        log_text = stderr_log.read_text()
        pytest.fail(f"Demo server did not start within 10 s.\nstderr:\n{log_text}")

    yield url

    # Teardown
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


# ── Route tests ──────────────────────────────────────────────────────────

def test_hub_returns_html(base_url):
    r = requests.get(f"{base_url}/hub")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("Content-Type", "")


def test_api_health(base_url):
    r = requests.get(f"{base_url}/api/health")
    assert r.status_code == 200
    data = r.json()
    assert "status" in data


def test_api_boot(base_url):
    r = requests.get(f"{base_url}/api/boot")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] in ("CLEAN", "MODIFIED")
    assert "merkle_root" in data


def test_api_tree(base_url):
    r = requests.get(f"{base_url}/api/tree")
    assert r.status_code == 200
    data = r.json()
    assert "branches" in data


def test_api_query(base_url):
    r = requests.post(f"{base_url}/api/query", json={"query": "test"})
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data.get("results"), list)


def test_api_adversarial(base_url):
    r = requests.get(f"{base_url}/api/adversarial")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data.get("counters"), list)
    assert isinstance(data.get("total_counters"), int)


def test_api_belief(base_url):
    r = requests.post(f"{base_url}/api/belief", json={"query": "test"})
    assert r.status_code == 200


def test_api_history(base_url):
    r = requests.get(f"{base_url}/api/history")
    assert r.status_code == 200


def test_api_search(base_url):
    r = requests.post(f"{base_url}/api/search", json={"query": "test"})
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data.get("results"), list)


def test_api_status(base_url):
    r = requests.get(f"{base_url}/api/status")
    assert r.status_code == 200


# ── Tamper detection ─────────────────────────────────────────────────────

def test_tamper_detection(base_url):
    tree_path = REPO_ROOT / "demo" / "demo_tree.json"
    original_bytes = tree_path.read_bytes()
    original_checksum = hashlib.sha256(original_bytes).hexdigest()

    try:
        tree = json.loads(original_bytes)
        # Get first branch, first leaf
        branch_name = next(iter(tree["branches"]))
        leaf = tree["branches"][branch_name]["leaves"][0]
        new_content = leaf["content"] + " TAMPERED"
        # Recompute leaf hash using named args
        leaf["hash"] = hash_leaf(
            content=new_content,
            branch=branch_name,
            timestamp=leaf["created"],
        )
        leaf["content"] = new_content
        tree_path.write_text(json.dumps(tree, ensure_ascii=False, indent=2))

        r = requests.get(f"{base_url}/api/boot")
        assert r.status_code == 200
        assert r.json()["status"] == "MODIFIED"
    finally:
        tree_path.write_bytes(original_bytes)
        restored_checksum = hashlib.sha256(tree_path.read_bytes()).hexdigest()
        assert restored_checksum == original_checksum, "demo_tree.json restore failed"
        r = requests.get(f"{base_url}/api/boot")
        assert r.json()["status"] == "CLEAN"
