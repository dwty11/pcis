#!/usr/bin/env python3
"""Tests for pcis sign CLI commands — key-dir / key-path flags."""

import json
import os
import subprocess
import sys

import pytest

nacl = pytest.importorskip("nacl", reason="PyNaCl not installed — skipping signing CLI tests")

CLI = [sys.executable, "-m", "pcis.cli"]


def run_cli(args, base_dir=None):
    """Helper to run CLI and return (stdout, stderr, returncode)."""
    cmd = CLI[:]
    if base_dir:
        cmd += ["--dir", str(base_dir)]
    cmd += args
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode


@pytest.fixture
def fresh_tree(tmp_path):
    """Initialize a fresh PCIS tree in a temp dir."""
    subprocess.run(CLI + ["--dir", str(tmp_path), "init"], check=True, capture_output=True)
    return tmp_path


# -----------------------------------------------------------------------
# sign init --key-dir
# -----------------------------------------------------------------------


class TestSignInit:
    def test_sign_init_default_writes_to_data(self, fresh_tree):
        """Default behaviour is unchanged: keypair lands in <base>/data/."""
        out, _err, rc = run_cli(["sign", "init"], base_dir=fresh_tree)
        assert rc == 0, out
        priv = fresh_tree / "data" / "pcis_signing.key"
        pub = fresh_tree / "data" / "pcis_signing.pub"
        assert priv.exists(), f"Private key not found at default location: {priv}"
        assert pub.exists(), f"Public key not found at default location: {pub}"

    def test_sign_init_key_dir_flag(self, tmp_path):
        """--key-dir must place the keypair in the given directory."""
        key_dir = tmp_path / "off_machine_keys"
        out, err, rc = run_cli(["sign", "init", "--key-dir", str(key_dir)], base_dir=tmp_path)
        assert rc == 0, f"sign init --key-dir failed:\nstdout: {out}\nstderr: {err}"
        priv = key_dir / "pcis_signing.key"
        pub = key_dir / "pcis_signing.pub"
        assert priv.exists(), (
            f"--key-dir={key_dir}: private key not found at {priv}\nstdout: {out}\nstderr: {err}"
        )
        assert pub.exists(), (
            f"--key-dir={key_dir}: public key not found at {pub}\nstdout: {out}\nstderr: {err}"
        )
        # Must NOT land in data/
        assert not (tmp_path / "data" / "pcis_signing.key").exists(), (
            "Private key leaked into data/ despite --key-dir"
        )

    def test_sign_init_key_dir_flag_error_if_exists(self, tmp_path):
        """Re-running sign init with the same --key-dir must raise FileExistsError."""
        key_dir = tmp_path / "keys"
        run_cli(["sign", "init", "--key-dir", str(key_dir)], base_dir=tmp_path)
        out, err, rc = run_cli(["sign", "init", "--key-dir", str(key_dir)], base_dir=tmp_path)
        assert rc == 1, f"Should have failed on existing key: {out}"
        assert "Error:" in out or "FileExistsError" in out or "already exists" in out, (
            f"Expected FileExistsError message, got:\nstdout: {out}\nstderr: {err}"
        )


# -----------------------------------------------------------------------
# sign root --key-path
# -----------------------------------------------------------------------


class TestSignRoot:
    def test_sign_root_default(self, fresh_tree):
        """Default behaviour: sign with key from <base>/data/."""
        run_cli(["sign", "init"], base_dir=fresh_tree)
        out, err, rc = run_cli(["sign", "root"], base_dir=fresh_tree)
        assert rc == 0, f"sign root failed:\nstdout: {out}\nstderr: {err}"
        assert "Root signed:" in out

    def test_sign_root_key_path_flag(self, tmp_path):
        """--key-path must sign with the specified private key."""
        key_dir = tmp_path / "keys"
        out_init, _err, _rc = run_cli(
            ["sign", "init", "--key-dir", str(key_dir)], base_dir=tmp_path
        )
        priv_key = key_dir / "pcis_signing.key"
        assert priv_key.exists(), f"Key not generated: {priv_key}"

        # Sign with the custom path
        out, err, rc = run_cli(
            ["sign", "root", "--key-path", str(priv_key)], base_dir=tmp_path
        )
        assert rc == 0, f"sign root --key-path failed:\nstdout: {out}\nstderr: {err}"
        assert "Root signed:" in out, f"Expected 'Root signed' in output, got: {out}"

    def test_sign_root_wrong_key_path(self, tmp_path):
        """sign root --key-path with a non-existent path must exit non-zero."""
        fake_key = tmp_path / "nonexistent.key"
        out, err, rc = run_cli(
            ["sign", "root", "--key-path", str(fake_key)], base_dir=tmp_path
        )
        assert rc == 1, f"Should have failed with non-existent key: {out}\nstderr: {err}"
        assert "Error:" in out or "not found" in out.lower(), (
            f"Expected error message, got:\nstdout: {out}\nstderr: {err}"
        )


# -----------------------------------------------------------------------
# sign verify --key-path
# -----------------------------------------------------------------------


class TestSignVerify:
    def test_sign_verify_default_finds_pub_in_data(self, tmp_path):
        """Default behaviour: verify uses <base>/data/pcis_signing.pub.

        Note: the default sign+verify integration has a pre-existing file-name mismatch
        (sign root writes root_signature.json; verify reads approved_root_cert.json).
        These tests cover the --key-path flag in isolation; the full integration
        path is tested in test_signing.py via the Python API.
        """
        run_cli(["sign", "init"], base_dir=tmp_path)
        pub = tmp_path / "data" / "pcis_signing.pub"
        assert pub.exists(), "Default init must create pub in data/"
        # sign verify with no cert present should fail gracefully
        out, err, rc = run_cli(["sign", "verify"], base_dir=tmp_path)
        assert rc == 1, f"sign verify should fail with no cert: {out}"
        assert "INVALID" in out, f"Expected INVALID message, got: {out}"

    def test_sign_verify_key_path_flag(self, tmp_path):
        """--key-path must use the specified public key for verification."""
        key_dir = tmp_path / "keys"
        run_cli(["sign", "init", "--key-dir", str(key_dir)], base_dir=tmp_path)

        pub_key = key_dir / "pcis_signing.pub"
        assert pub_key.exists(), f"Key not generated at {pub_key}"
        # With --key-path pointing to the pub key but no cert written yet, verify
        # should fail gracefully (not crash on the missing cert)
        out, err, rc = run_cli(
            ["sign", "verify", "--key-path", str(pub_key)], base_dir=tmp_path
        )
        assert rc == 1, f"sign verify --key-path should fail with no cert:\nstdout: {out}\nstderr: {err}"
        assert "INVALID" in out or "no approved_root_cert" in out, (
            f"Expected INVALID message, got: {out}\nstderr: {err}"
        )

    def test_sign_verify_unknown_flag(self, tmp_path):
        """--key-path must be recognised (not raise 'unrecognized argument')."""
        run_cli(["sign", "init"], base_dir=tmp_path)
        pub = tmp_path / "data" / "pcis_signing.pub"
        out, err, rc = run_cli(
            ["sign", "verify", "--key-path", str(pub)], base_dir=tmp_path
        )
        # Must NOT fail with argparse "unrecognized argument"
        assert "unrecognized arguments" not in err, (
            f"--key-path flag should be recognised:\nstderr: {err}"
        )
