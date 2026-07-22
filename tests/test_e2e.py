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


# ── Per-test copy of the demo tree ───────────────────────────────────────
# Every e2e test operates on its OWN copy in tmp_path, and the server is pointed at
# that copy via PCIS_DEMO_TREE_FILE. The shipped demo/demo_tree.json is never mutated,
# so the suite is safe even when a runner shares ONE workspace across the parallel
# matrix jobs (the GitVerse case). No shared-file backup/restore is needed.

@pytest.fixture()
def served_tree(tmp_path):
    dst = tmp_path / "demo_tree.json"
    shutil.copy2(REPO_ROOT / "demo" / "demo_tree.json", dst)
    os.chmod(dst, 0o644)  # copy2 preserves source mode; the copy must be writable to tamper
    return dst


# ── Server fixture (function-scoped) ─────────────────────────────────────

def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# NOTE: named e2e_base_url, NOT base_url — the pytest-base-url plugin (which can
# land in the env as an unpinned transitive dep) ships a session-scoped `base_url`
# fixture. A same-named function-scoped fixture here collides with it (ScopeMismatch,
# errors every e2e test). We don't own that name; keep ours prefixed. Do not rename back.
@pytest.fixture()
def e2e_base_url(served_tree, tmp_path):
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
            env={**os.environ, "PCIS_DEMO_TREE_FILE": str(served_tree)},
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

def test_front_door_serves_html_without_hub(e2e_base_url):
    # A fresh clone / CI has NO hub.html — it's gitignored (deployment-specific).
    # Reproduce that condition by hiding hub.html, then require the front door
    # (/, /hub, /demo) to serve HTML and never 500. Regression guard for the
    # "advertised URL 500s on arrival" bug: previously / redirected to /hub,
    # which send_file'd the missing hub.html straight into a 500.
    hub = REPO_ROOT / "demo" / "hub.html"
    hidden = hub.with_name("hub.html.hidden") if hub.exists() else None
    if hidden:
        hub.rename(hidden)
    try:
        for route in ("/", "/hub", "/demo"):
            r = requests.get(f"{e2e_base_url}{route}")
            assert r.status_code == 200, f"{route} returned {r.status_code} (front door broken on a clone)"
            assert "text/html" in r.headers.get("Content-Type", ""), \
                f"{route} content-type: {r.headers.get('Content-Type')}"
    finally:
        if hidden:
            hidden.rename(hub)


def test_api_health(e2e_base_url):
    r = requests.get(f"{e2e_base_url}/api/health")
    assert r.status_code == 200
    data = r.json()
    assert "status" in data


def test_api_boot(e2e_base_url):
    r = requests.get(f"{e2e_base_url}/api/boot")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] in ("CLEAN", "MODIFIED")
    assert "merkle_root" in data


def test_api_tree(e2e_base_url):
    r = requests.get(f"{e2e_base_url}/api/tree")
    assert r.status_code == 200
    data = r.json()
    assert "branches" in data


def test_api_query(e2e_base_url):
    r = requests.post(f"{e2e_base_url}/api/query", json={"query": "test"})
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data.get("results"), list)


def test_api_adversarial(e2e_base_url):
    r = requests.get(f"{e2e_base_url}/api/adversarial")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data.get("counters"), list)
    assert isinstance(data.get("total_counters"), int)


def test_api_adversarial_lights_up(e2e_base_url):
    # After the demo tree is reseeded, the Adversarial tab has real content:
    # >=3 COUNTERs and each resolves its challenged 'original' leaf.
    r = requests.get(f"{e2e_base_url}/api/adversarial")
    assert r.status_code == 200
    data = r.json()
    assert data["total_counters"] >= 3, data
    assert len(data["counters"]) >= 1
    assert data["counters"][0]["original"] is not None


def test_api_status_last_gardener_run_non_null(e2e_base_url):
    # status must surface a real last_gardener_run (from the shipped
    # external_validation_run.json), not a hardcoded null.
    r = requests.get(f"{e2e_base_url}/api/status")
    assert r.status_code == 200
    assert r.json()["last_gardener_run"] is not None


def test_api_belief(e2e_base_url):
    r = requests.post(f"{e2e_base_url}/api/belief", json={"query": "test"})
    assert r.status_code == 200


def test_api_history(e2e_base_url):
    r = requests.get(f"{e2e_base_url}/api/history")
    assert r.status_code == 200


def test_api_search(e2e_base_url):
    r = requests.post(f"{e2e_base_url}/api/search", json={"query": "test"})
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data.get("results"), list)


def test_api_status(e2e_base_url):
    r = requests.get(f"{e2e_base_url}/api/status")
    assert r.status_code == 200


# ── Tamper detection ─────────────────────────────────────────────────────

def test_tamper_detection(e2e_base_url, served_tree):
    tree_path = served_tree  # a per-test copy — never the shipped demo/demo_tree.json
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

        r = requests.get(f"{e2e_base_url}/api/boot")
        assert r.status_code == 200
        assert r.json()["status"] == "MODIFIED"
    finally:
        tree_path.write_bytes(original_bytes)
        restored_checksum = hashlib.sha256(tree_path.read_bytes()).hexdigest()
        assert restored_checksum == original_checksum, "demo_tree.json restore failed"
        r = requests.get(f"{e2e_base_url}/api/boot")
        assert r.json()["status"] == "CLEAN"
