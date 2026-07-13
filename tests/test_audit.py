#!/usr/bin/env python3
"""Tests for core/audit.py — Phase 3 audit bundle export + cross-verify."""

import json
import os
import subprocess
import sys
import zipfile

import pytest

pytest.importorskip("nacl", reason="PyNaCl not installed — skipping audit tests")

# Make core/ + pcis/ importable
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, _ROOT)


# -----------------------------------------------------------------------
# Fixture — minimal valid PCIS state at tmp_path:
#   data/tree.json (5 default branches, 2 with leaves, 3 empty)
#   data/pcis_signing.key + .pub (via generate_keypair)
#   data/root_signature.json (via sign_root)
#   data/events.action.jsonl (2 emitted events)
# -----------------------------------------------------------------------


@pytest.fixture
def tmp_audit_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("PCIS_BASE_DIR", str(tmp_path))
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    from knowledge_tree import (
        DEFAULT_BRANCHES,
        add_knowledge,
        compute_branch_hash,
        compute_root_hash,
        now_utc,
    )

    tree = {
        "version": 1,
        "created": now_utc(),
        "last_updated": now_utc(),
        "root_hash": "",
        "instance": "audit-test",
        "branches": {},
    }
    for branch in DEFAULT_BRANCHES:
        tree["branches"][branch] = {"hash": "", "leaves": []}

    add_knowledge(tree, "technical", "test leaf 1", confidence=0.85)
    add_knowledge(tree, "lessons", "test leaf 2", confidence=0.90)

    for bname in tree["branches"]:
        tree["branches"][bname]["hash"] = compute_branch_hash(
            tree["branches"][bname]["leaves"]
        )
    tree["root_hash"] = compute_root_hash(tree)

    tree_path = data_dir / "tree.json"
    with open(tree_path, "w") as f:
        json.dump(tree, f, indent=2)

    from signing import generate_keypair, sign_root

    priv_path, pub_path = generate_keypair(key_dir=str(data_dir))
    sig_result = sign_root()
    sig_path = data_dir / "root_signature.json"

    from events import emit_escalation

    journal_path = data_dir / "events.action.jsonl"
    emit_escalation(agent_id="gardener", reason="A", journal_path=str(journal_path))
    emit_escalation(agent_id="gardener", reason="B", journal_path=str(journal_path))

    return {
        "base": tmp_path,
        "data": data_dir,
        "tree_path": str(tree_path),
        "sig_path": str(sig_path),
        "journal_path": str(journal_path),
        "pub_path": pub_path,
        "priv_path": priv_path,
        "root_hash": sig_result["root_hash"],
    }


# -----------------------------------------------------------------------
# 1. create_bundle — file exists, manifest parses, all 5 files present
# -----------------------------------------------------------------------


def test_create_bundle_writes_zip_with_5_files(tmp_audit_setup):
    from audit import create_bundle

    output = str(tmp_audit_setup["base"] / "test.belief.bundle")
    result = create_bundle(
        tree_path=tmp_audit_setup["tree_path"],
        sig_path=tmp_audit_setup["sig_path"],
        journal_path=tmp_audit_setup["journal_path"],
        pub_key_path=tmp_audit_setup["pub_path"],
        output_path=output,
    )

    assert result["ok"] is True
    assert os.path.exists(output)
    assert result["leaf_count"] == 2
    assert result["event_count"] == 2
    assert result["root_hash"] == tmp_audit_setup["root_hash"]

    with zipfile.ZipFile(output) as zf:
        names = set(zf.namelist())
        assert names == {
            "manifest.json",
            "tree_snapshot.belief.jsonl",
            "events.action.jsonl",
            "root_signature.json",
            "pcis_signing.pub",
        }
        manifest = json.loads(zf.read("manifest.json"))
        assert "pcis_version" in manifest
        assert "export_timestamp" in manifest
        assert manifest["root_hash"] == tmp_audit_setup["root_hash"]
        assert "branches" in manifest
        assert isinstance(manifest["branches"], list)
        assert len(manifest["branches"]) == 5  # all 5 default branches preserved
        assert "files" in manifest
        for fname in (
            "tree_snapshot.belief.jsonl",
            "events.action.jsonl",
            "root_signature.json",
            "pcis_signing.pub",
        ):
            assert fname in manifest["files"]
            assert len(manifest["files"][fname]) == 64  # sha256 hex


# -----------------------------------------------------------------------
# 2. verify_bundle — all 4 layers ok
# -----------------------------------------------------------------------


def test_verify_bundle_all_layers_ok(tmp_audit_setup):
    from audit import create_bundle, verify_bundle

    output = str(tmp_audit_setup["base"] / "test.belief.bundle")
    create_bundle(
        tmp_audit_setup["tree_path"],
        tmp_audit_setup["sig_path"],
        tmp_audit_setup["journal_path"],
        tmp_audit_setup["pub_path"],
        output,
    )

    result = verify_bundle(output)

    assert result["overall"] == "ok"
    assert result["layers"]["snapshot"]["status"] == "ok"
    assert result["layers"]["signature"]["status"] == "ok"
    assert result["layers"]["events_chain"]["status"] == "ok"
    assert result["layers"]["cross_check"]["status"] == "ok"


# -----------------------------------------------------------------------
# 3. Tamper detection — modify a leaf in snapshot, snapshot layer fails
# -----------------------------------------------------------------------


def test_tamper_detection_snapshot_layer_fails(tmp_audit_setup):
    from audit import create_bundle, verify_bundle

    output = str(tmp_audit_setup["base"] / "test.belief.bundle")
    create_bundle(
        tmp_audit_setup["tree_path"],
        tmp_audit_setup["sig_path"],
        tmp_audit_setup["journal_path"],
        tmp_audit_setup["pub_path"],
        output,
    )

    with zipfile.ZipFile(output, "r") as zf:
        contents = {name: zf.read(name) for name in zf.namelist()}

    snapshot_text = contents["tree_snapshot.belief.jsonl"].decode("utf-8")
    lines = snapshot_text.splitlines()
    leaf = json.loads(lines[0])
    leaf["content"] = "TAMPERED CONTENT"
    lines[0] = json.dumps(
        leaf, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    contents["tree_snapshot.belief.jsonl"] = (
        "\n".join(lines) + "\n"
    ).encode("utf-8")

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in contents.items():
            zf.writestr(name, data)

    result = verify_bundle(output)
    assert result["overall"] == "fail"
    assert result["layers"]["snapshot"]["status"] == "fail"


# -----------------------------------------------------------------------
# 4. Missing/empty journal — events_chain returns warn, overall still ok
# -----------------------------------------------------------------------


def test_empty_journal_yields_warn_not_fail(tmp_audit_setup):
    from audit import create_bundle, verify_bundle

    empty_journal = str(tmp_audit_setup["data"] / "empty.jsonl")
    open(empty_journal, "w").close()  # empty file

    output = str(tmp_audit_setup["base"] / "test.belief.bundle")
    create_bundle(
        tmp_audit_setup["tree_path"],
        tmp_audit_setup["sig_path"],
        empty_journal,
        tmp_audit_setup["pub_path"],
        output,
    )

    result = verify_bundle(output)
    assert result["layers"]["events_chain"]["status"] == "warn"
    assert result["overall"] == "ok"


# -----------------------------------------------------------------------
# 5. CLI audit export — subprocess, exit 0, bundle exists
# -----------------------------------------------------------------------


def test_cli_audit_export_creates_bundle_at_default_path(tmp_audit_setup):
    cli_script = os.path.join(_ROOT, "pcis", "cli.py")

    result = subprocess.run(
        [
            sys.executable,
            cli_script,
            "--dir",
            str(tmp_audit_setup["base"]),
            "audit",
            "export",
            "--key",
            tmp_audit_setup["pub_path"],
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"

    audit_dir = tmp_audit_setup["data"] / "audit"
    bundles = list(audit_dir.glob("*.belief.bundle"))
    assert len(bundles) == 1, f"expected 1 bundle, found {bundles}"
    assert "Bundle written" in result.stdout
    assert "root_hash" in result.stdout
    assert "leaves" in result.stdout
    assert "events" in result.stdout


# -----------------------------------------------------------------------
# 6. CLI audit verify — subprocess on valid bundle, exit 0, "VERIFIED" in stdout
# -----------------------------------------------------------------------


def test_cli_audit_verify_prints_verified(tmp_audit_setup):
    cli_script = os.path.join(_ROOT, "pcis", "cli.py")

    export = subprocess.run(
        [
            sys.executable,
            cli_script,
            "--dir",
            str(tmp_audit_setup["base"]),
            "audit",
            "export",
            "--key",
            tmp_audit_setup["pub_path"],
        ],
        capture_output=True,
        text=True,
    )
    assert export.returncode == 0, f"export stderr: {export.stderr}"

    audit_dir = tmp_audit_setup["data"] / "audit"
    bundles = list(audit_dir.glob("*.belief.bundle"))
    assert len(bundles) == 1
    bundle_path = bundles[0]

    verify = subprocess.run(
        [
            sys.executable,
            cli_script,
            "--dir",
            str(tmp_audit_setup["base"]),
            "audit",
            "verify",
            str(bundle_path),
        ],
        capture_output=True,
        text=True,
    )

    assert verify.returncode == 0, (
        f"verify stderr: {verify.stderr}\nstdout: {verify.stdout}"
    )
    assert "VERIFIED" in verify.stdout


# -----------------------------------------------------------------------
# 7. Embedded-key forge vector (adversarial finding #4) — the signature layer
#    must verify against the on-disk PINNED .pub, NOT the public_key embedded
#    in root_signature.json. A forged cert (attacker key signing attacker root)
#    is internally consistent (snapshot + cross_check pass), so it isolates the
#    signature layer.
# -----------------------------------------------------------------------


def _keypair():
    import nacl.encoding
    import nacl.signing

    sk = nacl.signing.SigningKey.generate()
    pub = sk.verify_key.encode(encoder=nacl.encoding.HexEncoder).decode()
    return sk, pub


def _build_consistent_tree(data_dir, content):
    """A tree whose leaf/branch/root hashes are self-consistent, so the snapshot
    layer recomputes to the manifest root (the attacker controls the whole tree)."""
    from knowledge_tree import (
        DEFAULT_BRANCHES,
        add_knowledge,
        compute_branch_hash,
        compute_root_hash,
        now_utc,
    )

    tree = {
        "version": 1,
        "created": now_utc(),
        "last_updated": now_utc(),
        "root_hash": "",
        "instance": "forge-test",
        "branches": {},
    }
    for b in DEFAULT_BRANCHES:
        tree["branches"][b] = {"hash": "", "leaves": []}
    add_knowledge(tree, "technical", content, confidence=0.99)
    for bn in tree["branches"]:
        tree["branches"][bn]["hash"] = compute_branch_hash(tree["branches"][bn]["leaves"])
    tree["root_hash"] = compute_root_hash(tree)
    p = os.path.join(str(data_dir), "forged_tree.json")
    with open(p, "w") as f:
        json.dump(tree, f, indent=2)
    return p, tree["root_hash"]


def _write_root_signature(path, root_hash, sk):
    sig_hex = sk.sign(root_hash.encode()).signature.hex()
    import nacl.encoding

    pub_hex = sk.verify_key.encode(encoder=nacl.encoding.HexEncoder).decode()
    with open(path, "w") as f:
        json.dump(
            {
                "root_hash": root_hash,
                "signature": sig_hex,
                "signed_at": "2026-07-13T00:00:00+00:00",
                "public_key": pub_hex,
            },
            f,
            indent=2,
        )
    return pub_hex


def test_forged_bundle_signature_rejected_under_pin(tmp_audit_setup):
    """Attacker forges tree + signs its root with a key THEY control, embedding that
    key in root_signature.json and pcis_signing.pub. The pinned anchor
    (data/pcis_signing.pub) is the LEGIT key. The signature layer must REJECT it."""
    from audit import create_bundle, verify_bundle

    data = tmp_audit_setup["data"]  # already holds data/pcis_signing.pub = LEGIT (pinned) key
    sk_forged, pub_forged = _keypair()
    forged_tree, forged_root = _build_consistent_tree(
        data, "FORGED belief injected by an attacker"
    )
    forged_sig = os.path.join(str(data), "forged_root_signature.json")
    _write_root_signature(forged_sig, forged_root, sk_forged)
    forged_pub = os.path.join(str(data), "forged_pcis_signing.pub")
    with open(forged_pub, "w") as f:
        f.write(pub_forged)

    out = str(tmp_audit_setup["base"] / "forged.belief.bundle")
    create_bundle(forged_tree, forged_sig, tmp_audit_setup["journal_path"], forged_pub, out)
    result = verify_bundle(out)

    # Internally consistent → these pass, isolating the signature layer as the discriminator.
    assert result["layers"]["snapshot"]["status"] == "ok"
    assert result["layers"]["cross_check"]["status"] == "ok"
    # THE GUARANTEE: verified against the pinned key → the forged (non-pinned) sig fails.
    assert result["layers"]["signature"]["status"] == "fail", (
        "forged bundle signed by a NON-pinned key was accepted — embedded-key trust vector open"
    )
    assert result["overall"] == "fail"


def test_missing_pinned_pub_refuses_no_embedded_fallback(tmp_audit_setup):
    """If the on-disk pinned .pub is absent, the signature layer HARD-FAILS — never a
    fallback to the key embedded in the signature file."""
    from audit import create_bundle, verify_bundle

    out = str(tmp_audit_setup["base"] / "legit.belief.bundle")
    create_bundle(
        tmp_audit_setup["tree_path"],
        tmp_audit_setup["sig_path"],
        tmp_audit_setup["journal_path"],
        tmp_audit_setup["pub_path"],
        out,
    )
    os.remove(os.path.join(str(tmp_audit_setup["data"]), "pcis_signing.pub"))  # drop the pin
    result = verify_bundle(out)
    assert result["layers"]["signature"]["status"] == "fail"
    detail = result["layers"]["signature"]["detail"].lower()
    assert "embedded" in detail or "absent" in detail or "pinned" in detail
