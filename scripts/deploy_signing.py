#!/usr/bin/env python3
"""
deploy_signing.py — Deploy ed25519 root signing to an arbitrary PCIS tree.

Unlike core/signing.py (which assumes the canonical layout
<base>/data/tree.json + <base>/data/root_signature.json), this script accepts
an arbitrary tree path and writes the signature artifact next to that tree.

Use this when deploying signing onto a tree that is not at the default
location — e.g. a single-instance production tree living outside data/.

Usage:
    python3 scripts/deploy_signing.py --tree /path/to/tree.json
    python3 scripts/deploy_signing.py --tree ... --key-dir ~/.pcis-keys/
    python3 scripts/deploy_signing.py --tree ... --dry-run
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# Make core/ importable regardless of how this script is invoked
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, _ROOT)


DEFAULT_KEY_DIR = os.path.expanduser("~/.pcis-keys")
SIGNATURE_BASENAME = "root_signature.json"


def _signature_path_for_tree(tree_path):
    """Place root_signature.json in the same directory as the tree file."""
    return os.path.join(
        os.path.dirname(os.path.abspath(tree_path)), SIGNATURE_BASENAME
    )


def deploy_signing(tree_path, key_dir, dry_run=False):
    """Sign the Merkle root of the tree at tree_path using the keypair in key_dir.

    Returns a dict containing root_hash, signature, signed_at, public_key, valid.
    On dry_run, returns {"root_hash": ..., "dry_run": True} and writes nothing.
    """
    # Imports deferred so the module can be imported in environments without nacl
    from signing import (
        generate_keypair,
        verify_root_standalone,
        PRIVATE_KEY_FILE,
        PUBLIC_KEY_FILE,
    )
    from knowledge_tree import load_tree, compute_root_hash
    import nacl.encoding
    import nacl.signing

    priv_path = os.path.join(key_dir, PRIVATE_KEY_FILE)
    pub_path = os.path.join(key_dir, PUBLIC_KEY_FILE)
    sig_path = _signature_path_for_tree(tree_path)

    # Step 1: ensure keypair exists (generate only if absent)
    keys_existed = os.path.exists(priv_path) and os.path.exists(pub_path)
    if not keys_existed:
        if dry_run:
            pass  # would generate; skipping under dry-run
        else:
            generate_keypair(key_dir=key_dir)

    # Step 2: load tree, compute root
    tree = load_tree(tree_path)
    root_hash = compute_root_hash(tree)

    if dry_run:
        return {
            "root_hash": root_hash,
            "signed_at": None,
            "valid": None,
            "dry_run": True,
            "would_generate_keypair": not keys_existed,
            "would_write_signature_to": sig_path,
        }

    # Step 3: sign
    with open(priv_path, "r") as f:
        key_hex = f.read().strip()
    signing_key = nacl.signing.SigningKey(key_hex, encoder=nacl.encoding.HexEncoder)
    signed = signing_key.sign(root_hash.encode())
    signature_hex = signed.signature.hex()

    public_key_hex = signing_key.verify_key.encode(
        encoder=nacl.encoding.HexEncoder
    ).decode()

    signed_at = datetime.now(timezone.utc).isoformat()

    payload = {
        "root_hash": root_hash,
        "signature": signature_hex,
        "signed_at": signed_at,
        "public_key": public_key_hex,
    }

    # Step 4: write next to tree
    os.makedirs(os.path.dirname(sig_path), exist_ok=True)
    with open(sig_path, "w") as f:
        json.dump(payload, f, indent=2)

    # Step 5: verify round-trip
    verify = verify_root_standalone(root_hash, signature_hex, public_key_hex)
    payload["valid"] = bool(verify["valid"])
    payload["signature_path"] = sig_path
    return payload


def main():
    parser = argparse.ArgumentParser(
        description="Deploy ed25519 root signing against an arbitrary PCIS tree path."
    )
    parser.add_argument("--tree", required=True, help="Path to the tree.json file")
    parser.add_argument(
        "--key-dir",
        default=DEFAULT_KEY_DIR,
        help=f"Directory holding pcis_signing.key/.pub (default: {DEFAULT_KEY_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen, don't write any files",
    )
    args = parser.parse_args()

    if not os.path.exists(args.tree):
        print(f"Error: tree file not found: {args.tree}", file=sys.stderr)
        sys.exit(1)

    result = deploy_signing(args.tree, args.key_dir, dry_run=args.dry_run)

    if args.dry_run:
        print(f"  root_hash : {result['root_hash'][:16]}…  (dry-run, not signed)")
        print(f"  signed_at : (dry-run, not written)")
        print(f"  valid     : (dry-run, not verified)")
        sys.exit(0)

    print(f"  root_hash : {result['root_hash'][:16]}…")
    print(f"  signed_at : {result['signed_at']}")
    print(f"  valid     : {result['valid']}")
    if not result["valid"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
