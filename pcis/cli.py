#!/usr/bin/env python3
"""
pcis — CLI for Persistent Cognitive Integrity System.

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
    pcis healthcheck
    pcis drift [--model MODEL]
    pcis status
    pcis export [--format FORMAT]
"""

import argparse
import hashlib
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


def _is_pcis_source_repo(path):
    """True if `path` is the PCIS source checkout — its data/ is demo/working space
    (or, on a maintainer's box, a real substrate), never a place for a new user's tree."""
    return (os.path.exists(os.path.join(path, "demo", "demo_tree.json")) and
            os.path.exists(os.path.join(path, "core", "gardener.py")))


def _guard_not_source_repo(args):
    """Refuse to write a user's tree into the PCIS source repo's data/. Skipped when the
    base is chosen explicitly (--dir or PCIS_BASE_DIR) — that is a deliberate choice."""
    explicit = bool(getattr(args, "dir", None)) or ("PCIS_BASE_DIR" in os.environ)
    if not explicit and _is_pcis_source_repo(os.getcwd()):
        print("⚠️  This is the PCIS source repo — refusing to write a tree into its data/")
        print("   (that directory is demo/working space, not your knowledge).")
        print("   Point PCIS at a directory of your own and re-run:")
        print("     export PCIS_BASE_DIR=~/my-pcis        # then: pcis init")
        print("     # or one-off:  pcis --dir ~/my-pcis init")
        sys.exit(1)


def cmd_init(args):
    """Initialize a new PCIS knowledge tree."""
    _guard_not_source_repo(args)
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
    _guard_not_source_repo(args)
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
    """Verify tree integrity — re-derives every hash from leaf content."""
    _set_base_dir(args)
    from knowledge_tree import load_tree, compute_root_hash, verify_tree_integrity

    tree = load_tree()
    ok, errors = verify_tree_integrity(tree)
    root = compute_root_hash(tree)

    if ok:
        print(f"✅ CLEAN — tree integrity verified: {root[:24]}...")
    else:
        print(f"🔴 TAMPERED — integrity check failed ({len(errors)} error(s)):")
        for e in errors:
            print(f"   - {e}")
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

    if args.status:
        from belief_decay import decay_status
        status = decay_status(half_life_days=args.half_life)
        print(f"Decay Status (half-life={args.half_life} days)")
        print(f"  Total leaves: {status['total']}")
        print(f"  Exempt leaves: {status['exempt']}")
        print(f"  Below 0.5 confidence: {status['thresholds'][0.5]}")
        print(f"  Below 0.3 confidence: {status['thresholds'][0.3]}")
        print(f"  Below 0.1 confidence: {status['thresholds'][0.1]}")
        return

    if args.report:
        from belief_decay import decay_report
        report = decay_report(half_life_days=args.half_life)
        if not report:
            print("No non-exempt leaves found.")
            return
        print(f"Decay Report (half-life={args.half_life} days)")
        print(f"{'Leaf ID':>14}  {'Branch':>14}  {'Old':>6}  {'New':>6}  {'Age':>8}")
        print("-" * 60)
        for entry in report:
            print(f"  {entry['leaf_id'][:12]:>12}  {entry['branch']:>14}  "
                  f"{entry['old_conf']:.3f}  {entry['new_conf']:.3f}  "
                  f"{entry['age_days']:7.1f}d")
        return

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


def cmd_healthcheck(args):
    """Check gardener operational health."""
    _set_base_dir(args)
    from gardener_healthcheck import check as check_health

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
    from knowledge_tree import load_tree, compute_root_hash, verify_tree_integrity

    tree = load_tree()
    branches = tree.get("branches", {})
    total = sum(len(b.get("leaves", [])) for b in branches.values())
    root = compute_root_hash(tree)
    ok, _integrity_errors = verify_tree_integrity(tree)
    integrity = "✅ CLEAN" if ok else "🔴 TAMPERED"

    # Synapse count
    try:
        from knowledge_synapses import load_synapses
        syn = load_synapses()
        syn_count = len(syn.get("synapses", []))
    except Exception:
        syn_count = "?"

    # Healthcheck (read-only probe — status must not write the health flag)
    try:
        from gardener_healthcheck import probe as _health_probe
        health_status, _ = _health_probe()
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

    if not ok:
        sys.exit(1)


def cmd_ingest(args):
    """Ingest a document (text, PDF, or markdown) into the knowledge tree."""
    _set_base_dir(args)
    sys.path.insert(0, os.path.join(_ROOT, "core"))
    from doc_ingest import ingest_file

    path = os.path.abspath(args.file)
    if not os.path.exists(path):
        print(f"File not found: {path}")
        sys.exit(1)

    print(f"Ingesting: {path}")
    result = ingest_file(
        path,
        branch=args.branch,
    )

    print(f"\nExtracted {result['count']} claims from {result['source']}:")
    for i, leaf in enumerate(result["leaves"], 1):
        print(f"  {i}. [{leaf['id'][:8]}] {leaf['content'][:80]}")
    print(f"\nTree root hash: {result['root_hash'][:24]}...")
    if "chunks" in result:
        print(f"Markdown chunks processed: {result['chunks']}")


def cmd_sign_init(args):
    """Generate ed25519 signing keypair."""
    _set_base_dir(args)
    sys.path.insert(0, os.path.join(_ROOT, "core"))
    from signing import generate_keypair

    try:
        priv_path, pub_path = generate_keypair()
        print(f"Keypair generated:")
        print(f"  Private key: {priv_path}")
        print(f"  Public key:  {pub_path}")
        print(f"\nKeep the private key safe. Share the public key freely.")
    except FileExistsError as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_sign_root(args):
    """Sign the current Merkle root."""
    _set_base_dir(args)
    sys.path.insert(0, os.path.join(_ROOT, "core"))
    from signing import sign_root

    try:
        result = sign_root()
        print(f"Root signed:")
        print(f"  Root hash:  {result['root_hash'][:24]}...")
        print(f"  Signature:  {result['signature'][:24]}...")
        print(f"  Signed at:  {result['signed_at']}")
        print(f"  Public key: {result['public_key'][:24]}...")
    except (FileNotFoundError, RuntimeError) as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_sign_verify(args):
    """Verify the approved-root cert (data/approved_root_cert.json) against the on-disk PINNED
    key and the current tree. Runs the full-claim check via signing.verify_claim — pinned key
    (no embedded-key trust), signature over canonical(claim), claim-hash consistency, and
    tree-consistency (the signed tree_snapshot_sha256 + root_hash re-verified against the actual
    tree bytes). The CLI uses the same canonical-verification function any external caller
    uses, so multiple verify paths agree by construction."""
    _set_base_dir(args)
    sys.path.insert(0, os.path.join(_ROOT, "core"))
    from signing import (
        APPROVED_CERT_FILE,
        PUBLIC_KEY_FILE,
        _default_key_path,
        _tree_file,
        verify_claim,
    )

    cert_path = _default_key_path(APPROVED_CERT_FILE)
    pub_path = _default_key_path(PUBLIC_KEY_FILE)
    # Snapshot binds tree-consistency to the same bytes the approved root was signed over.
    # Configurable via PCIS_TREE_FILE (default: <base>/data/tree.json).
    tree_path = _tree_file()

    if not os.path.exists(cert_path):
        print(f"INVALID — no approved_root_cert.json at {cert_path}")
        sys.exit(1)
    if not os.path.exists(pub_path):
        print(f"INVALID — pinned public key absent: {pub_path} (refusing embedded-key trust)")
        sys.exit(1)

    with open(cert_path) as f:
        cert = json.load(f)
    with open(pub_path) as f:
        pin_fpr = hashlib.sha256(f.read().strip().encode()).hexdigest()

    ok, detail = verify_claim(cert, pin_fpr, tree_path if os.path.exists(tree_path) else None)
    if ok:
        print(f"VALID — {detail}")
    else:
        print(f"INVALID — {detail}")
        sys.exit(1)


def cmd_sign_pubkey(args):
    """Print public key hex for sharing."""
    _set_base_dir(args)
    sys.path.insert(0, os.path.join(_ROOT, "core"))
    from signing import export_public_key

    try:
        pub_hex = export_public_key()
        print(pub_hex)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_events_emit(args):
    """Emit an ESCALATION_SENT event."""
    _set_base_dir(args)
    sys.path.insert(0, os.path.join(_ROOT, "core"))
    from events import emit_escalation

    ev = emit_escalation(
        agent_id=args.agent,
        reason=args.reason,
        leaf_id=args.leaf,
        branch=args.branch,
    )
    prev = ev["prev_event_hash"]
    prev_disp = f"{prev[:16]}…" if prev else "null"
    print(f"ESCALATION_SENT  [{ev['event_id']}]")
    print(f"  agent     : {ev['agent_id']}")
    print(f"  reason    : {ev['reason']}")
    print(f"  leaf      : {ev['leaf_id'] or '-'}")
    print(f"  branch    : {ev['branch'] or '-'}")
    print(f"  hash      : {ev['event_hash'][:16]}…")
    print(f"  prev_hash : {prev_disp}")


def cmd_events_resolve(args):
    """Emit an ESCALATION_RESOLVED event referencing a prior SENT."""
    _set_base_dir(args)
    sys.path.insert(0, os.path.join(_ROOT, "core"))
    from events import resolve_escalation

    try:
        ev = resolve_escalation(
            event_id=args.event_id,
            resolution=args.resolution,
            agent_id=args.agent,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"ESCALATION_RESOLVED  [{ev['event_id']}]")
    print(f"  resolves    : {args.event_id}")
    print(f"  agent       : {ev['agent_id']}")
    print(f"  resolution  : {ev['resolution']}")
    print(f"  leaf        : {ev['leaf_id'] or '-'}")
    print(f"  branch      : {ev['branch'] or '-'}")
    print(f"  hash        : {ev['event_hash'][:16]}…")
    print(f"  prev_hash   : {ev['prev_event_hash'][:16]}…")


def cmd_events_list(args):
    """Print every event in the journal, one per line."""
    _set_base_dir(args)
    sys.path.insert(0, os.path.join(_ROOT, "core"))
    from events import load_journal

    events = load_journal()
    if not events:
        print("Journal is empty.")
        return
    for ev in events:
        kind = ev["event_type"].replace("ESCALATION_", "").lower()
        leaf = (ev.get("leaf_id") or "-")[:12]
        branch = ev.get("branch") or "-"
        agent = ev.get("agent_id") or "-"
        print(
            f"{ev['timestamp']}  {kind:9}  "
            f"agent={agent:10}  branch={branch:14}  "
            f"leaf={leaf:12}  [{ev['event_hash'][:8]}]"
        )


def cmd_events_verify_chain(args):
    """Verify the events journal hash chain."""
    _set_base_dir(args)
    sys.path.insert(0, os.path.join(_ROOT, "core"))
    from events import verify_chain

    result = verify_chain()
    icon = "✅" if result["valid"] else "🔴"
    print(f"{icon} {result['detail']} (events={result['events']})")
    if not result["valid"]:
        sys.exit(1)


def cmd_actions_list(args):
    """List actions in the action log (most recent first)."""
    _set_base_dir(args)
    sys.path.insert(0, os.path.join(_ROOT, "core"))
    from action_log import load_action_log

    events = load_action_log(args.journal)
    if not events:
        print("Journal is empty.")
        return

    limit = args.limit
    events = list(reversed(events))[:limit]

    for ev in events:
        ts = ev.get("timestamp", "")
        agent = ev.get("agent_id", "-")
        if ev["event_type"] == "ACTION_STARTED":
            tool = ev.get("tool_name", "-")
            evid = (ev.get("event_id") or "")[:6]
            print(f"{ts}  STARTED    {agent}  {tool}  (id: {evid})")
        elif ev["event_type"] == "ACTION_COMPLETED":
            severity = ev.get("outcome_severity", 0.0)
            delta = ev.get("confidence_delta")
            delta_str = f"delta={delta:+.3f}" if delta is not None else "delta=—"
            aid = (ev.get("action_id") or "")[:6]
            print(f"{ts}  COMPLETED  {agent}  {aid}  severity={severity:.2f}  {delta_str}")


def cmd_actions_verify_chain(args):
    """Verify the action log hash chain."""
    _set_base_dir(args)
    sys.path.insert(0, os.path.join(_ROOT, "core"))
    from action_log import verify_chain

    result = verify_chain(args.journal)
    print(f"Chain length : {result['length']}")
    print(f"Chain valid  : {result['valid']}")
    if not result["valid"]:
        broken = result.get("broken_at")
        if broken is not None:
            print(f"Broken at    : {broken}")
        sys.exit(1)


def cmd_audit_export(args):
    """Export an audit bundle (Phase 3)."""
    _set_base_dir(args)
    sys.path.insert(0, os.path.join(_ROOT, "core"))
    from audit import create_bundle

    base = os.environ["PCIS_BASE_DIR"]

    tree = args.tree or os.path.join(base, "data", "tree.json")
    sig = args.sig or os.path.join(base, "data", "root_signature.json")
    journal = args.journal or os.path.join(base, "data", "events.action.jsonl")
    key = args.key or os.path.join(base, "data", "pcis_signing.pub")   # pinned anchor, not the emptied ~/.pcis-keys

    if args.output:
        output = args.output
    else:
        from datetime import datetime, timezone
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        output = os.path.join(base, "data", "audit", f"{date_str}.belief.bundle")

    result = create_bundle(tree, sig, journal, key, output)

    if not result["ok"]:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    print(f"Bundle written: {result['bundle_path']}")
    print(f"  root_hash : {result['root_hash'][:16]}…")
    print(f"  leaves    : {result['leaf_count']}")
    print(f"  events    : {result['event_count']}")


def cmd_audit_verify(args):
    """Verify an audit bundle (Phase 3)."""
    _set_base_dir(args)
    sys.path.insert(0, os.path.join(_ROOT, "core"))
    from audit import verify_bundle

    result = verify_bundle(args.bundle_path)
    layers = result["layers"]

    def line(name, key):
        layer = layers[key]
        status = layer["status"]
        detail = layer.get("detail", "")
        if detail:
            print(f"{name:13}: {status}  ({detail})")
        else:
            print(f"{name:13}: {status}")

    line("snapshot", "snapshot")
    line("signature", "signature")
    line("events_chain", "events_chain")
    line("cross_check", "cross_check")
    print("------------------------------------")

    if result["overall"] == "ok":
        print("overall      : VERIFIED")
    else:
        print("overall      : FAIL")
        sys.exit(1)


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
        description="PCIS — Persistent Cognitive Integrity System",
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
    p.add_argument("--report", action="store_true", help="Show per-leaf decay details")
    p.add_argument("--status", action="store_true", help="Show confidence threshold summary")

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

    # healthcheck
    sub.add_parser("healthcheck", help="Check gardener health")

    # drift
    p = sub.add_parser("drift", help="Run identity drift monitor")
    p.add_argument("--model", help="Model to test against")

    # status
    sub.add_parser("status", help="Show PCIS status overview")

    # ingest
    p = sub.add_parser("ingest", help="Ingest a document (text, PDF, or markdown)")
    p.add_argument("file", help="Path to the file to ingest")
    p.add_argument("--branch", default=None, help="Target branch (default: ingested)")

    # export
    p = sub.add_parser("export", help="Export tree")
    p.add_argument("--format", default="json", help="Format: json, belief")

    # sign (subcommand group)
    sign_parser = sub.add_parser("sign", help="Ed25519 root signing")
    sign_sub = sign_parser.add_subparsers(dest="sign_command")
    sign_sub.add_parser("init", help="Generate ed25519 keypair")
    sign_sub.add_parser("root", help="Sign current Merkle root")
    sign_sub.add_parser("verify", help="Verify signature against current tree")
    sign_sub.add_parser("pubkey", help="Print public key hex")

    # events (subcommand group) — ESCALATION event journal
    events_parser = sub.add_parser("events", help="ESCALATION event journal")
    events_sub = events_parser.add_subparsers(dest="events_command")

    p = events_sub.add_parser("emit", help="Emit ESCALATION_SENT")
    p.add_argument("--agent", required=True, help="Agent ID emitting the escalation")
    p.add_argument("--reason", required=True, help="Why escalation was triggered")
    p.add_argument("--leaf", help="Leaf ID being escalated, if known")
    p.add_argument("--branch", help="Branch name")

    p = events_sub.add_parser("resolve", help="Emit ESCALATION_RESOLVED for a prior SENT")
    p.add_argument("--event-id", required=True, help="event_id of the SENT to resolve")
    p.add_argument("--agent", required=True, help="Agent ID resolving the escalation")
    p.add_argument("--resolution", required=True, help="Resolution text")

    events_sub.add_parser("list", help="List events in the journal")
    events_sub.add_parser("verify-chain", help="Verify the hash chain end-to-end")

    # audit (subcommand group) — Phase 3 audit bundle
    audit_parser = sub.add_parser("audit", help="Audit bundle export + cross-verify")
    audit_sub = audit_parser.add_subparsers(dest="audit_command")

    p = audit_sub.add_parser("export", help="Build a .belief.bundle from current state")
    p.add_argument("--tree", help="Path to tree.json (default: <BASE_DIR>/data/tree.json)")
    p.add_argument("--sig", help="Path to root_signature.json (default: <BASE_DIR>/data/root_signature.json)")
    p.add_argument("--journal", help="Path to events.action.jsonl (default: <BASE_DIR>/data/events.action.jsonl)")
    p.add_argument("--key", help="Path to pcis_signing.pub (default: <base>/data/pcis_signing.pub)")
    p.add_argument("--output", help="Output bundle path (default: <BASE_DIR>/data/audit/<YYYYMMDD>.belief.bundle)")

    p = audit_sub.add_parser("verify", help="Verify a .belief.bundle")
    p.add_argument("bundle_path", help="Path to the .belief.bundle file")

    # actions (subcommand group) — PCIS-internal action log
    actions_parser = sub.add_parser(
        "actions", help="Action log (PCIS-internal action audit)"
    )
    actions_sub = actions_parser.add_subparsers(dest="actions_command")

    p = actions_sub.add_parser("list", help="List actions (most recent first)")
    p.add_argument("--journal", help="Path to action_log.jsonl (default: <BASE_DIR>/data/action_log.jsonl)")
    p.add_argument("--limit", type=int, default=20, help="Max events to show (default: 20)")

    p = actions_sub.add_parser("verify-chain", help="Verify the action log hash chain")
    p.add_argument("--journal", help="Path to action_log.jsonl (default: <BASE_DIR>/data/action_log.jsonl)")

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
        "healthcheck": cmd_healthcheck,
        "drift": cmd_drift,
        "status": cmd_status,
        "export": cmd_export,
        "ingest": cmd_ingest,
    }

    # Handle 'sign' subcommand group
    if args.command == "sign":
        sign_commands = {
            "init": cmd_sign_init,
            "root": cmd_sign_root,
            "verify": cmd_sign_verify,
            "pubkey": cmd_sign_pubkey,
        }
        if not args.sign_command:
            sign_parser.print_help()
            sys.exit(0)
        sign_commands[args.sign_command](args)
        return

    # Handle 'events' subcommand group
    if args.command == "events":
        events_commands = {
            "emit": cmd_events_emit,
            "resolve": cmd_events_resolve,
            "list": cmd_events_list,
            "verify-chain": cmd_events_verify_chain,
        }
        if not args.events_command:
            events_parser.print_help()
            sys.exit(0)
        events_commands[args.events_command](args)
        return

    # Handle 'audit' subcommand group
    if args.command == "audit":
        audit_commands = {
            "export": cmd_audit_export,
            "verify": cmd_audit_verify,
        }
        if not args.audit_command:
            audit_parser.print_help()
            sys.exit(0)
        audit_commands[args.audit_command](args)
        return

    # Handle 'actions' subcommand group
    if args.command == "actions":
        actions_commands = {
            "list": cmd_actions_list,
            "verify-chain": cmd_actions_verify_chain,
        }
        if not args.actions_command:
            actions_parser.print_help()
            sys.exit(0)
        actions_commands[args.actions_command](args)
        return

    commands[args.command](args)


if __name__ == "__main__":
    main()
