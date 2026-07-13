#!/usr/bin/env python3
"""
audit.py — Phase 3: audit bundle export + cross-verify.

Two public functions:

    create_bundle(tree_path, sig_path, journal_path, pub_key_path, output_path)
        -> {"ok": True, "bundle_path", "root_hash", "leaf_count", "event_count"}
        | {"ok": False, "error": "..."}

    verify_bundle(bundle_path)
        -> {"overall": "ok"|"fail", "layers": {snapshot, signature, events_chain, cross_check}}

Bundle format (zip, .belief.bundle):
    - manifest.json
    - tree_snapshot.belief.jsonl   (canonical-JSON per leaf, sorted keys)
    - events.action.jsonl          (verbatim journal copy)
    - root_signature.json          (verbatim signature copy)
    - pcis_signing.pub             (verbatim public key)

Verify layers (each pass/fail independently):
    1. snapshot     — re-hash leaves, recompute root, must equal manifest.root_hash
    2. signature    — verify_root_standalone(recomputed_root, sig.signature, PINNED .pub)
                      (the on-disk pinned key, NOT the key embedded in the signature)
    3. events_chain — verify_chain over the bundled journal (empty journal = warn)
    4. cross_check  — root_signature.json root_hash must match snapshot root

overall is "ok" iff every layer is "ok" or "warn"; any "fail" -> "fail".

Zero deps outside stdlib + existing pcis core modules.
Private key path NEVER appears in any bundle file.
"""

import hashlib
import json
import os
import sys
import tempfile
import zipfile
from datetime import datetime, timezone

# Sibling core/ modules importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


PCIS_VERSION = "1.4.1"


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _canonical(obj):
    """Canonical JSON: sorted keys, no extra whitespace, UTF-8 safe."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _now_iso_utc():
    return datetime.now(timezone.utc).isoformat()


def _project_leaf(leaf, branch_name):
    """Project a tree leaf into the canonical snapshot shape.

    Renames `created` -> `created_at`. Defaults missing fields per spec:
      signed         -> False
      root_at_signing -> None  (null in JSON; not "")
    """
    return {
        "branch": branch_name,
        "confidence": leaf.get("confidence"),
        "content": leaf.get("content"),
        "created_at": leaf.get("created"),
        "hash": leaf.get("hash"),
        "id": leaf.get("id"),
        "root_at_signing": leaf.get("root_at_signing", None),
        "signed": leaf.get("signed", False),
        "source": leaf.get("source"),
    }


# -----------------------------------------------------------------------
# create_bundle
# -----------------------------------------------------------------------


def create_bundle(tree_path, sig_path, journal_path, pub_key_path, output_path):
    """Build a .belief.bundle zip. See module docstring for behaviour."""
    try:
        from knowledge_tree import compute_root_hash, load_tree

        if not os.path.exists(tree_path):
            return {"ok": False, "error": f"tree file not found: {tree_path}"}
        if not os.path.exists(sig_path):
            return {"ok": False, "error": f"signature file not found: {sig_path}"}
        if not os.path.exists(pub_key_path):
            return {"ok": False, "error": f"public key file not found: {pub_key_path}"}

        # Tree → snapshot
        tree = load_tree(tree_path)
        root_hash = compute_root_hash(tree)
        branches = tree.get("branches", {})
        branch_names = sorted(branches.keys())

        snapshot_lines = []
        leaf_count = 0
        for branch_name in branch_names:
            for leaf in branches[branch_name].get("leaves", []):
                snapshot_lines.append(_canonical(_project_leaf(leaf, branch_name)))
                leaf_count += 1
        if snapshot_lines:
            snapshot_bytes = ("\n".join(snapshot_lines) + "\n").encode("utf-8")
        else:
            snapshot_bytes = b""

        # Verbatim file reads
        with open(sig_path, "rb") as f:
            sig_bytes = f.read()
        with open(pub_key_path, "rb") as f:
            pub_bytes = f.read()

        if os.path.exists(journal_path):
            with open(journal_path, "rb") as f:
                journal_bytes = f.read()
        else:
            journal_bytes = b""

        event_count = sum(
            1 for line in journal_bytes.decode("utf-8", errors="ignore").splitlines()
            if line.strip()
        )

        # Manifest
        manifest = {
            "pcis_version": PCIS_VERSION,
            "export_timestamp": _now_iso_utc(),
            "root_hash": root_hash,
            "branches": branch_names,
            "files": {
                "tree_snapshot.belief.jsonl": _sha256_bytes(snapshot_bytes),
                "events.action.jsonl": _sha256_bytes(journal_bytes),
                "root_signature.json": _sha256_bytes(sig_bytes),
                "pcis_signing.pub": _sha256_bytes(pub_bytes),
            },
        }
        manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")

        # Write zip
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", manifest_bytes)
            zf.writestr("tree_snapshot.belief.jsonl", snapshot_bytes)
            zf.writestr("events.action.jsonl", journal_bytes)
            zf.writestr("root_signature.json", sig_bytes)
            zf.writestr("pcis_signing.pub", pub_bytes)

        return {
            "ok": True,
            "bundle_path": os.path.abspath(output_path),
            "root_hash": root_hash,
            "leaf_count": leaf_count,
            "event_count": event_count,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# -----------------------------------------------------------------------
# verify_bundle
# -----------------------------------------------------------------------


_REQUIRED_FILES = {
    "manifest.json",
    "tree_snapshot.belief.jsonl",
    "events.action.jsonl",
    "root_signature.json",
    "pcis_signing.pub",
}


def _empty_layers(detail):
    return {
        "snapshot":     {"status": "fail", "detail": detail},
        "signature":    {"status": "fail", "detail": detail},
        "events_chain": {"status": "fail", "detail": detail},
        "cross_check":  {"status": "fail", "detail": detail},
    }


def verify_bundle(bundle_path, public_key_path=None):
    """Verify a .belief.bundle. Returns the full layered status dict."""
    if not os.path.exists(bundle_path):
        return {
            "overall": "fail",
            "layers": _empty_layers(f"bundle not found: {bundle_path}"),
        }

    # Open zip + extract members
    try:
        with zipfile.ZipFile(bundle_path, "r") as zf:
            present = set(zf.namelist())
            missing = _REQUIRED_FILES - present
            if missing:
                return {
                    "overall": "fail",
                    "layers": _empty_layers(f"bundle missing files: {sorted(missing)}"),
                }
            manifest_bytes = zf.read("manifest.json")
            snapshot_bytes = zf.read("tree_snapshot.belief.jsonl")
            journal_bytes = zf.read("events.action.jsonl")
            sig_bytes = zf.read("root_signature.json")
            # NOTE: the signature layer verifies against the on-disk PINNED .pub
            # (public_key_path / _default_key_path), NOT the key embedded in
            # root_signature.json — see Layer 2 (adversarial finding #4).
    except zipfile.BadZipFile as e:
        return {"overall": "fail", "layers": _empty_layers(f"corrupt zip: {e}")}

    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as e:
        return {
            "overall": "fail",
            "layers": _empty_layers(f"manifest parse error: {e}"),
        }

    layers = {
        "snapshot":     {"status": "fail", "detail": ""},
        "signature":    {"status": "fail", "detail": ""},
        "events_chain": {"status": "fail", "detail": ""},
        "cross_check":  {"status": "fail", "detail": ""},
    }

    # ── Layer 1: snapshot ──────────────────────────────────────────────
    from knowledge_tree import compute_branch_hash, compute_root_hash, hash_leaf

    manifest_branches = manifest.get("branches", [])
    leaves_by_branch = {b: [] for b in manifest_branches}

    snapshot_text = snapshot_bytes.decode("utf-8")
    snapshot_failed = False
    snapshot_detail = ""
    recomputed_root = None

    for line in snapshot_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            leaf = json.loads(line)
        except json.JSONDecodeError as e:
            snapshot_failed = True
            snapshot_detail = f"snapshot line parse error: {e}"
            break

        branch = leaf.get("branch")
        if branch is None:
            snapshot_failed = True
            snapshot_detail = "snapshot leaf missing 'branch' field"
            break

        # Re-hash from canonical inputs
        try:
            expected = hash_leaf(leaf["content"], branch, leaf["created_at"])
        except KeyError as e:
            snapshot_failed = True
            snapshot_detail = f"snapshot leaf missing field: {e}"
            break

        stored = leaf.get("hash")
        if expected != stored:
            snapshot_failed = True
            snapshot_detail = (
                f"leaf {str(leaf.get('id'))[:12]} in {branch}: hash mismatch "
                f"(recomputed {expected[:12]}…, stored {str(stored)[:12]}…)"
            )
            break

        if branch not in leaves_by_branch:
            leaves_by_branch[branch] = []
        leaves_by_branch[branch].append(leaf)

    if not snapshot_failed:
        recomputed_branches = {}
        for branch_name, leaves in leaves_by_branch.items():
            min_leaves = [{"hash": l["hash"]} for l in leaves]
            recomputed_branches[branch_name] = {
                "hash": compute_branch_hash(min_leaves),
                "leaves": min_leaves,
            }
        recomputed_root = compute_root_hash({"branches": recomputed_branches})
        manifest_root = manifest.get("root_hash")
        if recomputed_root != manifest_root:
            snapshot_failed = True
            snapshot_detail = (
                f"recomputed root {recomputed_root[:16]}… does not match "
                f"manifest root_hash {str(manifest_root)[:16]}…"
            )
            recomputed_root = None

    if snapshot_failed:
        layers["snapshot"] = {"status": "fail", "detail": snapshot_detail}
    else:
        layers["snapshot"] = {"status": "ok", "detail": ""}

    # ── Layer 2: signature ─────────────────────────────────────────────
    try:
        sig_data = json.loads(sig_bytes)
    except json.JSONDecodeError as e:
        sig_data = None
        layers["signature"] = {
            "status": "fail",
            "detail": f"signature file parse error: {e}",
        }

    if sig_data is not None:
        if recomputed_root is None:
            layers["signature"] = {
                "status": "fail",
                "detail": "snapshot failed; cannot verify signature against recomputed root",
            }
        else:
            try:
                from signing import (
                    PUBLIC_KEY_FILE,
                    _default_key_path,
                    verify_root_standalone,
                )
                # Verify against the on-disk PINNED public key — NOT the public_key
                # embedded in root_signature.json. A self-embedded key lets a forged
                # cert validate under its own key (adversarial finding #4). Absent pin
                # is a hard fail, not an embedded-key fallback — mirrors verify_root.
                pin_path = public_key_path or _default_key_path(PUBLIC_KEY_FILE)
                if not os.path.exists(pin_path):
                    layers["signature"] = {
                        "status": "fail",
                        "detail": f"pinned public key absent: {pin_path} — refusing embedded-key fallback.",
                    }
                else:
                    with open(pin_path, "r") as pf:
                        pinned_pub = pf.read().strip()
                    if not pinned_pub:
                        layers["signature"] = {
                            "status": "fail",
                            "detail": "pinned public key empty — refusing embedded-key fallback.",
                        }
                    else:
                        sig_result = verify_root_standalone(
                            recomputed_root, sig_data["signature"], pinned_pub
                        )
                        if sig_result["valid"]:
                            layers["signature"] = {
                                "status": "ok",
                                "detail": f"signed {sig_data.get('signed_at', '')}",
                            }
                        else:
                            layers["signature"] = {
                                "status": "fail",
                                "detail": sig_result.get("detail", "signature invalid vs pinned key"),
                            }
            except Exception as e:
                layers["signature"] = {
                    "status": "fail",
                    "detail": f"signature verify raised: {e}",
                }

    # ── Layer 3: events_chain ──────────────────────────────────────────
    with tempfile.NamedTemporaryFile(
        suffix=".jsonl", delete=False
    ) as tmp_journal:
        tmp_journal.write(journal_bytes)
        tmp_journal_path = tmp_journal.name
    try:
        from events import verify_chain
        chain_result = verify_chain(tmp_journal_path)
        if chain_result["events"] == 0:
            layers["events_chain"] = {
                "status": "warn",
                "detail": "journal is empty",
            }
        elif chain_result["valid"]:
            layers["events_chain"] = {
                "status": "ok",
                "detail": f"{chain_result['events']} events, chain intact",
            }
        else:
            layers["events_chain"] = {
                "status": "fail",
                "detail": chain_result.get("detail", "chain invalid"),
            }
    except Exception as e:
        layers["events_chain"] = {
            "status": "fail",
            "detail": f"verify_chain raised: {e}",
        }
    finally:
        try:
            os.unlink(tmp_journal_path)
        except OSError:
            pass

    # ── Layer 4: cross_check ───────────────────────────────────────────
    if sig_data is None:
        layers["cross_check"] = {
            "status": "fail",
            "detail": "signature file not parseable",
        }
    elif recomputed_root is None:
        layers["cross_check"] = {
            "status": "fail",
            "detail": "snapshot failed; cannot cross-check",
        }
    else:
        sig_root = sig_data.get("root_hash")
        if sig_root == recomputed_root:
            layers["cross_check"] = {"status": "ok", "detail": "roots match"}
        else:
            layers["cross_check"] = {
                "status": "fail",
                "detail": (
                    f"sig.root_hash ({str(sig_root)[:16]}…) does not match "
                    f"recomputed root ({recomputed_root[:16]}…)"
                ),
            }

    # ── Overall ────────────────────────────────────────────────────────
    statuses = {layer["status"] for layer in layers.values()}
    overall = "fail" if "fail" in statuses else "ok"

    return {"overall": overall, "layers": layers}
