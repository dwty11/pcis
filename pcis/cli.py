#!/usr/bin/env python3
"""
pcis — CLI for Persistent Cognitive Identity Systems.

Usage:
    pcis init [--dir PATH]
    pcis add <branch> <content> [--source SOURCE] [--confidence CONF]
    pcis show [BRANCH]
    pcis search <query> [--top-k N] [--branch BRANCH]
    pcis root
    pcis verify
    pcis proof <leaf_id>
    pcis assess <leaf_id>
    pcis prune <branch> <leaf_id>
    pcis decay [--half-life DAYS] [--dry-run]
    pcis link <from_id> <to_id> <relation> [--note NOTE]
    pcis links <leaf_id>
    pcis gardener [--dry-run] [--branch BRANCH] [--verbose]
    pcis gardener --gap-scan
    pcis connections [--limit N] [--dry-run]
    pcis healthcheck
    pcis drift [--model MODEL]
    pcis status
    pcis export [--format FORMAT]
"""

import argparse
import json
import os
import sys

# Ensure core/ is importable regardless of install mode
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, _ROOT)


def _set_base_dir(args):
    """Set PCIS_BASE_DIR from --dir flag or default."""
    if hasattr(args, "dir") and args.dir:
        os.environ["PCIS_BASE_DIR"] = os.path.abspath(args.dir)
    elif "PCIS_BASE_DIR" not in os.environ:
        os.environ["PCIS_BASE_DIR"] = os.getcwd()


def cmd_init(args):
    """Initialize a new PCIS knowledge tree."""
    _set_base_dir(args)
    base = os.environ["PCIS_BASE_DIR"]
    data_dir = os.path.join(base, "data")
    os.makedirs(data_dir, exist_ok=True)

    tree_file = os.path.join(data_dir, "tree.json")
    if os.path.exists(tree_file):
        print(f"Tree already exists: {tree_file}")
        return

    from knowledge_tree import DEFAULT_BRANCHES, now_utc, compute_root_hash

    tree = {
        "meta": {
            "created": now_utc(),
            "version": "1.1.0",
        },
        "branches": {},
    }
    for branch in DEFAULT_BRANCHES:
        tree["branches"][branch] = {"leaves": []}

    tree["root_hash"] = compute_root_hash(tree)

    with open(tree_file, "w") as f:
        json.dump(tree, f, indent=2, ensure_ascii=False)

    print(f"✅ Initialized PCIS tree at {tree_file}")
    print(f"   Branches: {', '.join(DEFAULT_BRANCHES)}")
    print(f"   Root hash: {tree['root_hash'][:24]}...")


def cmd_add(args):
    """Add knowledge to the tree."""
    _set_base_dir(args)
    from knowledge_tree import tree_lock, add_knowledge

    with tree_lock() as tree:
        leaf_id = add_knowledge(
            tree,
            args.branch,
            args.content,
            source=args.source or "cli",
            confidence=args.confidence,
        )

    print(f"✅ Added [{leaf_id[:12]}] to {args.branch} (conf={args.confidence})")


def cmd_show(args):
    """Show tree or a specific branch."""
    _set_base_dir(args)
    from knowledge_tree import load_tree, compute_root_hash

    tree = load_tree()
    branches = tree.get("branches", {})

    if args.branch:
        if args.branch not in branches:
            print(f"❌ Branch '{args.branch}' not found. Available: {', '.join(branches.keys())}")
            sys.exit(1)
        leaves = branches[args.branch].get("leaves", [])
        print(f"## {args.branch} ({len(leaves)} leaves)\n")
        for leaf in leaves:
            counter = " [COUNTER]" if leaf["content"].startswith("COUNTER:") else ""
            print(f"  [{leaf['id'][:12]}] conf={leaf['confidence']:.2f}{counter}")
            print(f"    {leaf['content'][:120]}")
            print()
    else:
        root = compute_root_hash(tree)
        total = sum(len(b.get("leaves", [])) for b in branches.values())
        print(f"PCIS Knowledge Tree — {total} leaves, {len(branches)} branches")
        print(f"Root: {root[:24]}...")
        print()
        for name, data in sorted(branches.items()):
            n = len(data.get("leaves", []))
            print(f"  {name:20} {n:4} leaves")


def cmd_search(args):
    """Search the knowledge tree."""
    _set_base_dir(args)
    from knowledge_search import search

    results = search(args.query, top_k=args.top_k, branch_filter=args.branch)

    if not results:
        print("No results found.")
        return

    print(f"Found {len(results)} result(s):\n")
    for score, leaf in results:
        print(f"  [{leaf['id'][:12]}] score={score:.3f} branch={leaf.get('branch', '?')}")
        print(f"    {leaf['content'][:150]}")
        print()


def cmd_root(args):
    """Print the current Merkle root hash."""
    _set_base_dir(args)
    from knowledge_tree import load_tree, compute_root_hash

    tree = load_tree()
    root = compute_root_hash(tree)
    print(root)


def cmd_verify(args):
    """Verify tree integrity."""
    _set_base_dir(args)
    from knowledge_tree import load_tree, compute_root_hash

    tree = load_tree()
    stored = tree.get("root_hash", "")
    computed = compute_root_hash(tree)

    if stored == computed:
        print(f"✅ CLEAN — root hash matches: {computed[:24]}...")
    else:
        print(f"🔴 TAMPERED — stored root does not match computed!")
        print(f"   Stored:   {stored[:24]}...")
        print(f"   Computed: {computed[:24]}...")
        sys.exit(1)


def cmd_proof(args):
    """Generate a Merkle inclusion proof for a leaf."""
    _set_base_dir(args)
    from knowledge_tree import load_tree, generate_inclusion_proof

    tree = load_tree()
    proof = generate_inclusion_proof(tree, args.leaf_id)

    if proof is None:
        print(f"❌ Leaf {args.leaf_id} not found.")
        sys.exit(1)

    print(json.dumps(proof, indent=2))


def cmd_assess(args):
    """Assess belief stance for a leaf via synapse traversal."""
    _set_base_dir(args)
    from belief_traversal import assess_belief

    result = assess_belief(args.leaf_id)

    print(f"Leaf: {args.leaf_id[:12]}")
    print(f"Stance: {result['stance']}")
    print(f"Effective confidence: {result['effective_confidence']:.3f}")
    print(f"Supporters: {result['support_count']}")
    print(f"Challengers: {result['challenge_count']}")
    if result.get("reasoning"):
        print(f"\nReasoning: {result['reasoning']}")


def cmd_prune(args):
    """Remove a leaf from the tree."""
    _set_base_dir(args)
    from knowledge_tree import tree_lock, prune_leaf

    with tree_lock() as tree:
        success = prune_leaf(tree, args.branch, args.leaf_id)

    if success:
        print(f"✅ Pruned [{args.leaf_id[:12]}] from {args.branch}")
    else:
        print(f"❌ Leaf {args.leaf_id} not found in {args.branch}")
        sys.exit(1)


def cmd_decay(args):
    """Apply belief decay to the tree."""
    _set_base_dir(args)
    from belief_decay import apply_decay_to_tree

    stats = apply_decay_to_tree(half_life_days=args.half_life, dry_run=args.dry_run)

    mode = "[DRY RUN] " if args.dry_run else ""
    print(f"{mode}Decay applied (half-life={args.half_life} days)")
    print(f"  Leaves processed: {stats['total']}")
    print(f"  Leaves decayed: {stats['updated']}")
    print(f"  Leaves exempt: {stats['skipped']}")


def cmd_link(args):
    """Create a synapse between two leaves."""
    _set_base_dir(args)
    from knowledge_synapses import load_synapses, save_synapses, add_synapse

    synapses = load_synapses()
    add_synapse(synapses, args.from_id, args.to_id, args.relation,
                note=args.note or "", source="cli")
    save_synapses(synapses)
    print(f"✅ {args.from_id[:12]} --[{args.relation}]--> {args.to_id[:12]}")


def cmd_links(args):
    """Show synapses for a leaf."""
    _set_base_dir(args)
    from knowledge_synapses import load_synapses

    synapses = load_synapses()
    related = [s for s in synapses.get("synapses", [])
               if s.get("from_leaf") == args.leaf_id or s.get("to_leaf") == args.leaf_id]

    if not related:
        print(f"No synapses found for {args.leaf_id[:12]}")
        return

    print(f"Synapses for [{args.leaf_id[:12]}]:\n")
    for s in related:
        direction = "→" if s.get("from_leaf") == args.leaf_id else "←"
        other = s.get("to_leaf") if direction == "→" else s.get("from_leaf")
        print(f"  {direction} [{other[:12]}] {s.get('relation', '?')} (conf={s.get('confidence', '?')})")
        if s.get("note"):
            print(f"    {s['note']}")


def cmd_gardener(args):
    """Run the adversarial gardener."""
    _set_base_dir(args)
    sys.argv = ["gardener.py"]
    if args.dry_run:
        sys.argv.append("--dry-run")
    if args.branch:
        sys.argv.extend(["--branch", args.branch])
    if args.verbose:
        sys.argv.append("--verbose")
    if args.gap_scan:
        sys.argv.append("--gap-scan")

    from gardener import main
    main()


def cmd_connections(args):
    """Run synapse discovery."""
    _set_base_dir(args)
    sys.argv = ["gardener_connections.py"]
    if args.dry_run:
        sys.argv.append("--dry-run")
    if args.limit:
        sys.argv.extend(["--limit", str(args.limit)])

    from gardener_connections import main
    main()


def cmd_healthcheck(args):
    """Check gardener operational health."""
    _set_base_dir(args)
    from gardener_healthcheck import check_health

    status, detail = check_health()
    icons = {"OK": "✅", "STALE": "⚠️", "ERROR": "🔴", "MISSING": "❓"}
    print(f"{icons.get(status, '?')} {status}: {detail}")
    if status not in ("OK",):
        sys.exit(1)


def cmd_drift(args):
    """Run identity drift monitor."""
    _set_base_dir(args)
    sys.argv = ["model_agnosticity_monitor.py"]
    if args.model:
        sys.argv.extend(["--model", args.model])

    from model_agnosticity_monitor import main
    main()


def cmd_status(args):
    """Show overall PCIS status."""
    _set_base_dir(args)
    from knowledge_tree import load_tree, compute_root_hash

    tree = load_tree()
    branches = tree.get("branches", {})
    total = sum(len(b.get("leaves", [])) for b in branches.values())
    root = compute_root_hash(tree)
    stored = tree.get("root_hash", "")
    integrity = "✅ CLEAN" if stored == root else "🔴 MISMATCH"

    # Synapse count
    try:
        from knowledge_synapses import load_synapses
        syn = load_synapses()
        syn_count = len(syn.get("synapses", []))
    except Exception:
        syn_count = "?"

    # Healthcheck
    try:
        from gardener_healthcheck import check_health
        health_status, _ = check_health()
    except Exception:
        health_status = "?"

    print("PCIS Status")
    print("─" * 40)
    print(f"  Leaves:      {total}")
    print(f"  Branches:    {len(branches)}")
    print(f"  Synapses:    {syn_count}")
    print(f"  Root:        {root[:24]}...")
    print(f"  Integrity:   {integrity}")
    print(f"  Gardener:    {health_status}")


def cmd_export(args):
    """Export the tree in a given format."""
    _set_base_dir(args)
    from knowledge_tree import load_tree

    tree = load_tree()

    if args.format == "json":
        print(json.dumps(tree, indent=2, ensure_ascii=False))
    elif args.format == "belief":
        from belief_history import export_belief_format
        print(export_belief_format(tree))
    else:
        print(f"❌ Unknown format: {args.format}. Use: json, belief")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="pcis",
        description="PCIS — Persistent Cognitive Identity Systems",
    )
    parser.add_argument("--dir", help="PCIS base directory (default: cwd or PCIS_BASE_DIR)")
    sub = parser.add_subparsers(dest="command")

    # init
    sub.add_parser("init", help="Initialize a new PCIS knowledge tree")

    # add
    p = sub.add_parser("add", help="Add knowledge to the tree")
    p.add_argument("branch", help="Branch name")
    p.add_argument("content", help="Knowledge content")
    p.add_argument("--source", default="cli", help="Source attribution")
    p.add_argument("--confidence", type=float, default=0.80, help="Confidence (0-1)")

    # show
    p = sub.add_parser("show", help="Show tree or branch")
    p.add_argument("branch", nargs="?", help="Branch to show (omit for overview)")

    # search
    p = sub.add_parser("search", help="Search knowledge")
    p.add_argument("query", help="Search query")
    p.add_argument("--top-k", type=int, default=5, help="Number of results")
    p.add_argument("--branch", help="Restrict to branch")

    # root
    sub.add_parser("root", help="Print Merkle root hash")

    # verify
    sub.add_parser("verify", help="Verify tree integrity")

    # proof
    p = sub.add_parser("proof", help="Generate inclusion proof")
    p.add_argument("leaf_id", help="Leaf ID")

    # assess
    p = sub.add_parser("assess", help="Assess belief stance")
    p.add_argument("leaf_id", help="Leaf ID")

    # prune
    p = sub.add_parser("prune", help="Remove a leaf")
    p.add_argument("branch", help="Branch name")
    p.add_argument("leaf_id", help="Leaf ID")

    # decay
    p = sub.add_parser("decay", help="Apply belief decay")
    p.add_argument("--half-life", type=int, default=180, help="Half-life in days")
    p.add_argument("--dry-run", action="store_true", help="Report only")

    # link
    p = sub.add_parser("link", help="Create synapse between leaves")
    p.add_argument("from_id", help="Source leaf ID")
    p.add_argument("to_id", help="Target leaf ID")
    p.add_argument("relation", help="Relation type (SUPPORTS, CONTRADICTS, REFINES, DERIVES_FROM)")
    p.add_argument("--note", help="Optional note")

    # links
    p = sub.add_parser("links", help="Show synapses for a leaf")
    p.add_argument("leaf_id", help="Leaf ID")

    # gardener
    p = sub.add_parser("gardener", help="Run adversarial gardener")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--branch", help="Focus on branch")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--gap-scan", action="store_true", help="Gap-scan mode")

    # connections
    p = sub.add_parser("connections", help="Run synapse discovery")
    p.add_argument("--limit", type=int, default=20, help="Max pairs to evaluate")
    p.add_argument("--dry-run", action="store_true")

    # healthcheck
    sub.add_parser("healthcheck", help="Check gardener health")

    # drift
    p = sub.add_parser("drift", help="Run identity drift monitor")
    p.add_argument("--model", help="Model to test against")

    # status
    sub.add_parser("status", help="Show PCIS status overview")

    # export
    p = sub.add_parser("export", help="Export tree")
    p.add_argument("--format", default="json", help="Format: json, belief")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "init": cmd_init,
        "add": cmd_add,
        "show": cmd_show,
        "search": cmd_search,
        "root": cmd_root,
        "verify": cmd_verify,
        "proof": cmd_proof,
        "assess": cmd_assess,
        "prune": cmd_prune,
        "decay": cmd_decay,
        "link": cmd_link,
        "links": cmd_links,
        "gardener": cmd_gardener,
        "connections": cmd_connections,
        "healthcheck": cmd_healthcheck,
        "drift": cmd_drift,
        "status": cmd_status,
        "export": cmd_export,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
