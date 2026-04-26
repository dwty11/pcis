#!/usr/bin/env python3
"""
back_sign_leaves.py — Mark every leaf in a tree as part of a signed batch.

For each leaf, sets:
    "signed":          True
    "root_at_signing": <Merkle root hash at the time this script ran>

We do NOT add per-leaf Ed25519 signatures (overkill, slow). The single
root_signature.json (produced by scripts/deploy_signing.py) cryptographically
covers the whole tree state at signing time. Each leaf's root_at_signing
field tells you which signed-root this leaf was last reaffirmed under.

Adding signed/root_at_signing to a leaf does NOT change the leaf's hash
(leaf hashes are computed from content + branch + timestamp only), so the
tree's root hash is preserved.

Usage:
    python3 scripts/back_sign_leaves.py --tree /path/to/tree.json
"""

import argparse
import os
import sys

# Make core/ importable regardless of how this script is invoked
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, _ROOT)


def back_sign_tree(tree_path):
    """Mark every leaf in the tree at tree_path with signed:True + root_at_signing.

    Uses tree_lock() for safe concurrent access. Returns the count of leaves marked.
    """
    from knowledge_tree import compute_root_hash, tree_lock

    count = 0
    with tree_lock(path=tree_path) as tree:
        # Compute the root before adding fields. Since signed/root_at_signing
        # don't enter the leaf hash, this equals the post-mutation root, but
        # capturing it once makes intent explicit.
        root_at_signing = compute_root_hash(tree)
        for branch in tree.get("branches", {}).values():
            for leaf in branch.get("leaves", []):
                leaf["signed"] = True
                leaf["root_at_signing"] = root_at_signing
                count += 1
    return count


def main():
    parser = argparse.ArgumentParser(
        description="Back-sign every leaf in a PCIS tree with the current root hash."
    )
    parser.add_argument("--tree", required=True, help="Path to tree.json")
    args = parser.parse_args()

    if not os.path.exists(args.tree):
        print(f"Error: tree file not found: {args.tree}", file=sys.stderr)
        sys.exit(1)

    count = back_sign_tree(args.tree)
    print(f"Back-signed {count} leaves in {args.tree}")


if __name__ == "__main__":
    main()
