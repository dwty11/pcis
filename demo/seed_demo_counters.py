#!/usr/bin/env python3
"""seed_demo_counters.py — reseed demo/demo_tree.json with hand-authored
synthetic COUNTER leaves, so the demo's Adversarial tab has real content to read.

⚠️  CONFIDENTIALITY NOTE — READ BEFORE EDITING.
EVERY counter below is HAND-AUTHORED SYNTHETIC FICTION challenging the demo
tree's OWN invented content: "Meridian Corp" and its fictional AI agents
(ATLAS, SENTINEL, COMPASS, FORGE, BRIDGE, ...). NONE of it is lifted, sampled,
paraphrased, or derived from any real / operator knowledge tree. This reseed is
the one place a shortcut could walk private content back into the public repo —
so it is authored by hand against the demo's fiction, and nothing else.

Hashes are machine-recomputed via core.knowledge_tree (never hand-typed).
Idempotent: re-running skips a counter whose challenged leaf already has one.

Usage:
    python3 demo/seed_demo_counters.py           # reseed in place
    python3 demo/seed_demo_counters.py --check    # exit 1 if not yet seeded
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(REPO_ROOT / "core"))

from knowledge_tree import hash_leaf, compute_branch_hash, compute_root_hash  # noqa: E402

DEMO_TREE = HERE / "demo_tree.json"
SOURCE = "gardener-demo-2026-04-07"

# --- HAND-AUTHORED SYNTHETIC COUNTERS -------------------------------------
# Each challenges a REAL demo leaf (by id) with a fresh adversarial argument
# ABOUT THE DEMO'S FICTION. Pure invention about Meridian Corp — no substrate.
SYNTHETIC_COUNTERS = [
    {
        "branch": "decisions",
        "challenged_id": "809bcf98d393",  # "Adopt Claude API ... competitive pricing at scale"
        "challenge": (
            "The 'competitive pricing at scale' rationale rests on list pricing, not "
            "Meridian's negotiated enterprise volume — and committing to a single provider "
            "forfeits exactly the pricing leverage a 2.3M-customer inference load would "
            "command. The decision standardizes before the platform's model-swap "
            "abstraction has been proven on more than a third of the fleet."
        ),
        "confidence": 0.60,
        "created": "2026-04-07 06:33:11 UTC",
    },
    {
        "branch": "risks",
        "challenged_id": "01f3a4ac52bf",  # "Prompt injection ... Patched within 48 hours"
        "challenge": (
            "Patching the discovered injection path 'within 48 hours' closes one instance, "
            "not the class. Multi-turn manipulation is a property of the interaction surface, "
            "not a single bug; without a standing adversarial-eval gate, a closed ticket reads "
            "as safety while the mechanism stays live."
        ),
        "confidence": 0.58,
        "created": "2026-04-07 06:33:12 UTC",
    },
    {
        "branch": "compliance",
        "challenged_id": "e927fef96ff5",  # "Employee AI usage policy finalized and distributed"
        "challenge": (
            "A 'finalized and distributed' policy measures publication, not adherence. The "
            "shadow-AI finding shows a third of staff already route work through personal "
            "tools; without enforcement telemetry, 'finalized' overstates coverage of the "
            "very behavior the policy exists to prevent."
        ),
        "confidence": 0.60,
        "created": "2026-04-07 06:33:13 UTC",
    },
    {
        "branch": "lessons",
        "challenged_id": "56c8472e7bda",  # "Customer trust drops sharply ... 34% reduced usage"
        "challenge": (
            "The claim generalizes a 34% figure from one post-incident survey. Severity, "
            "customer segment, and concurrent press coverage are uncontrolled; treating the "
            "number as a universal law risks over-investing in outreach theater instead of "
            "the underlying reliability fix."
        ),
        "confidence": 0.57,
        "created": "2026-04-07 06:33:14 UTC",
    },
    {
        "branch": "compliance",
        "challenged_id": "48e0c3176ec6",  # "EU AI Act ... SENTINEL high-risk ... Deadline August 2026"
        "challenge": (
            "The SENTINEL conformity timeline assumes a notified body is available on "
            "schedule. Article-6 high-risk assessment capacity has been the sector-wide "
            "bottleneck; an August deadline pinned to external throughput the program does "
            "not control is optimistic, not planned."
        ),
        "confidence": 0.59,
        "created": "2026-04-07 06:33:15 UTC",
    },
]


def _make_leaf(counter: dict) -> dict:
    branch = counter["branch"]
    created = counter["created"]
    content = f"COUNTER: [{counter['challenged_id']}] {counter['challenge']}"
    h = hash_leaf(content, branch, created)
    return {
        "id": h[:12],
        "hash": h,
        "content": content,
        "source": SOURCE,
        "confidence": counter["confidence"],
        "created": created,
        "promoted_to": None,
        "is_counter": True,
    }


def reseed(tree: dict) -> int:
    added = 0
    for counter in SYNTHETIC_COUNTERS:
        leaves = tree["branches"][counter["branch"]]["leaves"]
        already = any(
            l["content"].startswith(f"COUNTER: [{counter['challenged_id']}]")
            for l in leaves
        )
        if already:
            continue
        leaves.append(_make_leaf(counter))
        added += 1
    # Machine-recompute every branch hash + root + combined (never hand-typed).
    for branch in tree["branches"].values():
        branch["hash"] = compute_branch_hash(branch["leaves"])
    tree["root_hash"] = compute_root_hash(tree)
    synapse_root = hashlib.sha256(b"NO_SYNAPSES").hexdigest()
    tree["combined_root_hash"] = hashlib.sha256(
        (tree["root_hash"] + synapse_root).encode()
    ).hexdigest()
    tree["last_updated"] = "2026-04-07 06:33:15 UTC"
    return added


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Reseed demo tree with synthetic counters.")
    parser.add_argument("--check", action="store_true",
                        help="Exit 1 if the demo tree has fewer than the seeded counters.")
    args = parser.parse_args(argv)

    tree = json.loads(DEMO_TREE.read_text())

    if args.check:
        n = sum(1 for b in tree["branches"].values() for l in b["leaves"]
                if l["content"].startswith("COUNTER:"))
        print(f"{n} COUNTER leaf(ves) in demo tree")
        sys.exit(0 if n >= len(SYNTHETIC_COUNTERS) else 1)

    added = reseed(tree)
    DEMO_TREE.write_text(json.dumps(tree, ensure_ascii=False, indent=2) + "\n")
    print(f"Reseeded {DEMO_TREE.name}: +{added} synthetic COUNTER leaf(ves); "
          f"root -> {tree['root_hash'][:16]}...")


if __name__ == "__main__":
    main()
