#!/usr/bin/env python3
"""
a2a_demo.py — A2A handoff smoke test (Slide 7 demo).

Two agents, ephemeral Ed25519 keypairs, a Merkle-rooted knowledge tree.
Agent A signs the root with their private key. Agent B receives the tree
+ signature + Agent A's public key as a self-contained bundle, recomputes
the root from tree content, and verifies the signature.

No shared state. No live system access. Each side runs in its own block
of this script. The bundle written to disk between them is the only thing
that crosses the boundary — the same shape an A→B handoff would take in
production.

Usage:
    python3 scripts/a2a_demo.py                 # clean run, exits 0
    python3 scripts/a2a_demo.py --tamper        # flip a leaf, B catches it, exits 1
    python3 scripts/a2a_demo.py --bundle PATH   # write bundle to PATH (default: tempdir)

Wall-clock: ~1 second. Live demo budget: 60 seconds for narrative.
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

# Make sibling core/ importable regardless of cwd
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, _ROOT)


SEPARATOR = "─" * 60


def _hr(label: str) -> None:
    print(SEPARATOR)
    print(label)
    print(SEPARATOR)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="A2A handoff smoke test: A signs, B verifies, ephemeral keys."
    )
    parser.add_argument(
        "--tamper", action="store_true",
        help="Flip a leaf in the bundle between sign and verify — Agent B should detect it.",
    )
    parser.add_argument(
        "--bundle", default=None,
        help="Path to write the handoff bundle (default: <tmpdir>/a2a_handoff.json).",
    )
    args = parser.parse_args()

    # Lazy imports so missing-dependency errors are clear
    try:
        import nacl.encoding
        import nacl.signing
    except ImportError:
        print(
            "ERROR: PyNaCl not installed. Install with: pip install pcis[signing]",
            file=sys.stderr,
        )
        return 2

    from knowledge_tree import (
        DEFAULT_BRANCHES,
        add_knowledge,
        compute_branch_hash,
        compute_root_hash,
        hash_leaf,
        now_utc,
    )
    from signing import verify_root_standalone

    bundle_path = args.bundle or os.path.join(
        tempfile.gettempdir(), "a2a_handoff.json"
    )

    # ── Agent A ─────────────────────────────────────────────────────────
    _hr("AGENT A — knowledge holder")

    # 1. Ephemeral keypair
    a_signing_key = nacl.signing.SigningKey.generate()
    a_pub_hex = a_signing_key.verify_key.encode(
        encoder=nacl.encoding.HexEncoder
    ).decode()
    print(f"  [1] Generated ephemeral Ed25519 keypair")
    print(f"      pubkey: {a_pub_hex[:16]}…")

    # 2. Build a small knowledge tree
    tree = {
        "version": 1,
        "created": now_utc(),
        "last_updated": now_utc(),
        "root_hash": "",
        "instance": "agent-a",
        "branches": {},
    }
    for branch in DEFAULT_BRANCHES:
        tree["branches"][branch] = {"hash": "", "leaves": []}

    add_knowledge(tree, "technical",
                  "API responses validated server-side", confidence=0.9)
    add_knowledge(tree, "lessons",
                  "Always log inference timestamp in UTC", confidence=0.85)
    add_knowledge(tree, "constraints",
                  "All belief writes must go through tree_lock()", confidence=0.95)

    for bname in tree["branches"]:
        tree["branches"][bname]["hash"] = compute_branch_hash(
            tree["branches"][bname]["leaves"]
        )
    tree["root_hash"] = compute_root_hash(tree)

    leaf_count = sum(
        len(b.get("leaves", [])) for b in tree["branches"].values()
    )
    print(f"  [2] Built knowledge tree: {leaf_count} leaves across "
          f"{len(tree['branches'])} branches")
    print(f"      Merkle root: {tree['root_hash'][:24]}…")

    # 3. Sign the root
    signed = a_signing_key.sign(tree["root_hash"].encode())
    signature_hex = signed.signature.hex()
    signed_at = datetime.now(timezone.utc).isoformat()
    print(f"  [3] Signed root with Agent A's private key")
    print(f"      signature: {signature_hex[:24]}…  ({len(signature_hex)} hex chars)")

    # 4. Write the handoff bundle (this is the only thing crossing the wire)
    bundle = {
        "agent_id": "agent-a",
        "tree": tree,
        "signature": {
            "root_hash": tree["root_hash"],
            "signature": signature_hex,
            "signed_at": signed_at,
            "public_key": a_pub_hex,
        },
    }
    os.makedirs(os.path.dirname(os.path.abspath(bundle_path)) or ".", exist_ok=True)
    with open(bundle_path, "w") as f:
        json.dump(bundle, f, indent=2, ensure_ascii=False)
    print(f"  [4] Handoff bundle written → {bundle_path}")
    print(f"      ({os.path.getsize(bundle_path)} bytes)")

    # ── Optional tamper ─────────────────────────────────────────────────
    if args.tamper:
        print()
        _hr("⚠️  TAMPER PHASE — flipping a leaf between sign and verify")
        with open(bundle_path, "r") as f:
            data = json.load(f)
        target_branch = "lessons"
        leaves = data["tree"]["branches"].get(target_branch, {}).get("leaves", [])
        if not leaves:
            print(f"  [!] No leaves found to tamper in branch {target_branch!r}")
        else:
            original = leaves[0]["content"]
            leaves[0]["content"] = "TAMPERED — this was not signed by Agent A"
            print(f"  [!] Modified first leaf in branch {target_branch!r}:")
            print(f"      before: {original[:60]}")
            print(f"      after:  {leaves[0]['content']}")
        with open(bundle_path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # ── Agent B ─────────────────────────────────────────────────────────
    print()
    _hr("AGENT B — receives bundle, verifies independently")

    with open(bundle_path, "r") as f:
        received = json.load(f)
    received_tree = received["tree"]
    received_sig = received["signature"]
    print(f"  [5] Opened handoff bundle from Agent A")
    print(f"      claimed root: {received_sig['root_hash'][:24]}…")

    # 6. Re-hash every leaf from its content. Catches per-leaf tampering
    #    where the attacker forgot to (or couldn't) recompute the chain upward.
    for bname, branch in received_tree.get("branches", {}).items():
        for leaf in branch.get("leaves", []):
            expected = hash_leaf(leaf["content"], bname, leaf["created"])
            if expected != leaf.get("hash"):
                print(f"  [6] ❌ Leaf hash mismatch in branch {bname!r}:")
                print(f"          leaf id  : {str(leaf.get('id',''))[:12]}…")
                print(f"          stored   : {str(leaf.get('hash',''))[:24]}…")
                print(f"          recomputed: {expected[:24]}…")
                print()
                _hr("RESULT: ❌ TAMPER DETECTED at the leaf-hash layer")
                return 1
        # Recompute branch hash from the (now-verified) leaf hashes
        received_tree["branches"][bname]["hash"] = compute_branch_hash(
            branch.get("leaves", [])
        )

    recomputed_root = compute_root_hash(received_tree)
    print(f"  [6] Recomputed Merkle root from received tree content")
    print(f"      recomputed: {recomputed_root[:24]}…")

    # 7. Compare recomputed root to signed root
    if recomputed_root != received_sig.get("root_hash"):
        print(f"  [7] ❌ Recomputed root does NOT match signed root")
        print(f"      signed     : {str(received_sig.get('root_hash',''))[:24]}…")
        print(f"      recomputed : {recomputed_root[:24]}…")
        print()
        _hr("RESULT: ❌ TAMPER DETECTED at the root layer")
        return 1
    print(f"  [7] Recomputed root matches signed root ✓")

    # 8. Verify the Ed25519 signature with Agent A's public key.
    result = verify_root_standalone(
        recomputed_root, received_sig["signature"], received_sig["public_key"]
    )
    if not result.get("valid"):
        print(f"  [8] ❌ Signature verification failed: {result.get('detail','')}")
        print()
        _hr("RESULT: ❌ SIGNATURE INVALID")
        return 1
    print(f"  [8] Ed25519 signature verifies against Agent A's public key ✓")
    print(f"      signed at : {received_sig.get('signed_at','')}")

    # ── Result ──────────────────────────────────────────────────────────
    print()
    _hr("RESULT: ✅ A2A HANDOFF VERIFIED END-TO-END")
    print(f"  Agent A signed → Agent B verified, offline, no shared state.")
    print(f"  Bundle:        {bundle_path}")
    print(f"  Tree leaves:   {leaf_count}")
    print(f"  Verified root: {recomputed_root[:24]}…")
    print(f"  Verified key:  {received_sig['public_key'][:24]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
