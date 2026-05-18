"""Tests for pcis CLI."""

import json
import os
import subprocess
import sys
import tempfile

import pytest

CLI = [sys.executable, "-m", "pcis.cli"]


@pytest.fixture
def fresh_tree(tmp_path):
    """Initialize a fresh PCIS tree in a temp dir."""
    subprocess.run(CLI + ["--dir", str(tmp_path), "init"], check=True, capture_output=True)
    return tmp_path


def run_cli(args, base_dir=None):
    """Helper to run CLI and return (stdout, returncode)."""
    cmd = CLI[:]
    if base_dir:
        cmd += ["--dir", str(base_dir)]
    cmd += args
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout, result.returncode


class TestInit:
    def test_creates_tree(self, tmp_path):
        out, rc = run_cli(["init"], base_dir=tmp_path)
        assert rc == 0
        assert "Initialized" in out
        assert (tmp_path / "data" / "tree.json").exists()

    def test_refuses_double_init(self, fresh_tree):
        out, rc = run_cli(["init"], base_dir=fresh_tree)
        assert rc == 0
        assert "already exists" in out


class TestAdd:
    def test_adds_leaf(self, fresh_tree):
        out, rc = run_cli(["add", "lessons", "Test knowledge"], base_dir=fresh_tree)
        assert rc == 0
        assert "Added" in out

    def test_custom_confidence(self, fresh_tree):
        out, rc = run_cli(["add", "lessons", "High conf", "--confidence", "0.95"], base_dir=fresh_tree)
        assert rc == 0
        assert "conf=0.95" in out


class TestShow:
    def test_show_overview(self, fresh_tree):
        out, rc = run_cli(["show"], base_dir=fresh_tree)
        assert rc == 0
        assert "PCIS Knowledge Tree" in out
        assert "lessons" in out

    def test_show_branch(self, fresh_tree):
        run_cli(["add", "technical", "REST uses plural nouns"], base_dir=fresh_tree)
        out, rc = run_cli(["show", "technical"], base_dir=fresh_tree)
        assert rc == 0
        assert "REST uses plural nouns" in out

    def test_show_unknown_branch(self, fresh_tree):
        out, rc = run_cli(["show", "nonexistent"], base_dir=fresh_tree)
        assert rc == 1


class TestIntegrity:
    def test_verify_clean(self, fresh_tree):
        out, rc = run_cli(["verify"], base_dir=fresh_tree)
        assert rc == 0
        assert "CLEAN" in out

    def test_verify_tampered(self, fresh_tree):
        tree_file = fresh_tree / "data" / "tree.json"
        with open(tree_file) as f:
            tree = json.load(f)
        tree["root_hash"] = "deadbeef" * 8
        with open(tree_file, "w") as f:
            json.dump(tree, f)
        out, rc = run_cli(["verify"], base_dir=fresh_tree)
        assert rc == 1
        assert "TAMPERED" in out

    def test_root_hash(self, fresh_tree):
        out, rc = run_cli(["root"], base_dir=fresh_tree)
        assert rc == 0
        assert len(out.strip()) == 64  # SHA-256 hex


class TestStatus:
    def test_status_output(self, fresh_tree):
        out, rc = run_cli(["status"], base_dir=fresh_tree)
        assert rc == 0
        assert "Leaves:" in out
        assert "Branches:" in out
        assert "Integrity:" in out


class TestSearch:
    def test_search_no_results(self, fresh_tree):
        out, rc = run_cli(["search", "nonexistent topic"], base_dir=fresh_tree)
        assert rc == 0
        assert "No results" in out


class TestDecay:
    def test_decay_dry_run(self, fresh_tree):
        out, rc = run_cli(["decay", "--dry-run"], base_dir=fresh_tree)
        assert rc == 0
        assert "DRY RUN" in out


class TestExport:
    def test_export_json(self, fresh_tree):
        out, rc = run_cli(["export", "--format", "json"], base_dir=fresh_tree)
        assert rc == 0
        data = json.loads(out)
        assert "branches" in data
