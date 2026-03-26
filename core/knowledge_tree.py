#!/usr/bin/env python3
"""
knowledge_tree.py — Merkle Knowledge Tree

A structured knowledge store where every piece of knowledge:
- Has a hash (integrity)
- Knows where it came from (provenance)
- Knows when it was learned (temporality)
- Can be synced across instances (portability)

Usage:
    python3 knowledge_tree.py --add <branch> <knowledge> [--source <source>] [--confidence <0-1>]
    python3 knowledge_tree.py --show [branch]
    python3 knowledge_tree.py --root
    python3 knowledge_tree.py --diff <other_tree.json>
    python3 knowledge_tree.py --export
    python3 knowledge_tree.py --prune <branch> <leaf_id>
    python3 knowledge_tree.py --link <from_leaf_id> <to_leaf_id> <RELATION> [--note "..."] [--source "..."]
    python3 knowledge_tree.py --links <leaf_id>
    python3 knowledge_tree.py --assess <leaf_id>
    python3 knowledge_tree.py --query-belief <natural language query>
    python3 knowledge_tree.py --decay [--half-life 180] [--dry-run]

Examples:
    python3 knowledge_tree.py --add technical "REST endpoints should use plural nouns" --source "style-guide" --confidence 0.85
    python3 knowledge_tree.py --add lessons "Skimming time-sensitive data is a trust violation" --source "session-2026-03-03"
    python3 knowledge_tree.py --show technical
    python3 knowledge_tree.py --root
    python3 knowledge_tree.py --diff /path/to/other/knowledge_tree.json

No external dependencies. Python 3.8+.
"""

import fcntl
import hashlib
import json
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

BASE_DIR = os.environ.get("PCIS_BASE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TREE_FILE = os.path.join(BASE_DIR, "data", "tree.json")
TZ_UTC = timezone.utc

DEFAULT_BRANCHES = [
    "identity", "philosophy", "lessons", "technical", "relationships",
]


def now_utc():
    return datetime.now(TZ_UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def hash_leaf(content, branch, timestamp):
    data = f"{branch}:{timestamp}:{content}"
    return hashlib.sha256(data.encode()).hexdigest()


def compute_branch_hash(leaves):
    if not leaves:
        return hashlib.sha256(b"EMPTY_BRANCH").hexdigest()
    leaf_hashes = [leaf["hash"] for leaf in leaves]
    combined = "|".join(sorted(leaf_hashes))
    return hashlib.sha256(combined.encode()).hexdigest()


def compute_root_hash(tree):
    branches = tree.get("branches", {})
    branch_hashes = []
    for name in sorted(branches.keys()):
        branch = branches[name]
        branch_hashes.append(f"{name}:{branch.get('hash', 'EMPTY')}")
    if not branch_hashes:
        return hashlib.sha256(b"EMPTY_TREE").hexdigest()
    level = [hashlib.sha256(bh.encode()).hexdigest() for bh in branch_hashes]
    while len(level) > 1:
        next_level = []
        for i in range(0, len(level), 2):
            if i + 1 < len(level):
                combined = level[i] + level[i + 1]
            else:
                combined = level[i] + level[i]
            next_level.append(hashlib.sha256(combined.encode()).hexdigest())
        level = next_level
    return level[0]


def verify_tree_integrity(tree):
    """Recompute every hash from content up. Returns (ok, errors)."""
    errors = []
    for bname, branch in tree.get("branches", {}).items():
        for leaf in branch.get("leaves", []):
            expected = hash_leaf(leaf["content"], bname, leaf["created"])
            if expected != leaf["hash"]:
                errors.append(f"leaf {leaf['id']} in {bname}: content-hash mismatch")
        expected_bh = compute_branch_hash(branch["leaves"])
        if expected_bh != branch["hash"]:
            errors.append(f"branch {bname}: hash mismatch")
    expected_root = compute_root_hash(tree)
    if expected_root != tree.get("root_hash", ""):
        errors.append("root hash mismatch")
    return len(errors) == 0, errors


def load_tree(path=None):
    path = path or TREE_FILE
    if os.path.exists(path):
        with open(path, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError as e:
                print(f"Error: knowledge tree file is corrupted ({e}).")
                print(f"       Refusing to overwrite. Fix or remove {path} manually.")
                sys.exit(1)
    tree = {
        "version": 1,
        "created": now_utc(),
        "last_updated": now_utc(),
        "root_hash": "",
        "instance": "primary",
        "branches": {}
    }
    for branch in DEFAULT_BRANCHES:
        tree["branches"][branch] = {
            "hash": hashlib.sha256(b"EMPTY_BRANCH").hexdigest(),
            "leaves": []
        }
    tree["root_hash"] = compute_root_hash(tree)
    return tree


def save_tree(tree, path=None):
    """Save tree atomically with file locking.
    For multi-process safety, prefer tree_lock() context manager."""
    path = path or TREE_FILE
    lock_path = path + ".lock"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(lock_path, 'w') as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        _write_tree(tree, path)


def _write_tree(tree, path):
    """Write tree to disk (no locking). Called by save_tree and tree_lock."""
    tree["last_updated"] = now_utc()
    for branch_name in tree.get("branches", {}):
        tree["branches"][branch_name]["hash"] = compute_branch_hash(
            tree["branches"][branch_name]["leaves"]
        )
    tree["root_hash"] = compute_root_hash(tree)
    # Combined root: ties tree integrity to synapse integrity (Opus architecture, 2026-03-25)
    try:
        from core.knowledge_synapses import load_synapses, compute_synapses_root
        synapses = load_synapses()
        synapse_root = compute_synapses_root(synapses)
    except Exception:
        synapse_root = hashlib.sha256(b"NO_SYNAPSES").hexdigest()
    tree["combined_root_hash"] = hashlib.sha256(
        (tree["root_hash"] + synapse_root).encode()
    ).hexdigest()
    tmp_path = path + ".tmp"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(tree, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


@contextmanager
def tree_lock(path=None):
    """Acquire exclusive lock on tree file. Yields loaded tree, saves on exit."""
    path = path or TREE_FILE
    lock_path = path + ".lock"
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(lock_path, 'w') as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        tree = load_tree(path)
        yield tree
        _write_tree(tree, path)


def add_knowledge(tree, branch, content, source="session", confidence=0.7):
    if not content or not content.strip():
        raise ValueError("leaf content cannot be empty")
    if len(content) > 10_000:
        raise ValueError(f"leaf content too long ({len(content)} chars, max 10000)")
    if not branch or not branch.strip():
        raise ValueError("branch name cannot be empty")
    if not isinstance(confidence, (int, float)) or confidence < 0.0 or confidence > 1.0:
        raise ValueError(f"confidence must be between 0.0 and 1.0, got {confidence}")
    if branch not in tree["branches"]:
        tree["branches"][branch] = {"hash": "", "leaves": []}
    timestamp = now_utc()
    leaf_hash = hash_leaf(content, branch, timestamp)
    leaf_id = str(uuid.uuid4())
    leaf = {
        "id": leaf_id,
        "hash": leaf_hash,
        "content": content,
        "source": source,
        "confidence": confidence,
        "created": timestamp,
        "promoted_to": None
    }
    tree["branches"][branch]["leaves"].append(leaf)
    tree["branches"][branch]["hash"] = compute_branch_hash(
        tree["branches"][branch]["leaves"]
    )
    return leaf_id


def prune_leaf(tree, branch, leaf_id):
    if branch not in tree["branches"]:
        return False
    leaves = tree["branches"][branch]["leaves"]
    original_len = len(leaves)
    tree["branches"][branch]["leaves"] = [
        l for l in leaves if l["id"] != leaf_id
    ]
    if len(tree["branches"][branch]["leaves"]) < original_len:
        tree["branches"][branch]["hash"] = compute_branch_hash(
            tree["branches"][branch]["leaves"]
        )
        return True
    return False


def diff_trees(tree_a, tree_b):
    result = {
        "roots_match": tree_a.get("root_hash") == tree_b.get("root_hash"),
        "branches_only_in_a": [],
        "branches_only_in_b": [],
        "branches_diverged": [],
        "branches_identical": [],
        "leaves_only_in_a": {},
        "leaves_only_in_b": {},
    }
    branches_a = set(tree_a.get("branches", {}).keys())
    branches_b = set(tree_b.get("branches", {}).keys())
    result["branches_only_in_a"] = list(branches_a - branches_b)
    result["branches_only_in_b"] = list(branches_b - branches_a)
    for branch in branches_a & branches_b:
        hash_a = tree_a["branches"][branch].get("hash", "")
        hash_b = tree_b["branches"][branch].get("hash", "")
        if hash_a == hash_b:
            result["branches_identical"].append(branch)
        else:
            result["branches_diverged"].append(branch)
            ids_a = {l["id"] for l in tree_a["branches"][branch]["leaves"]}
            ids_b = {l["id"] for l in tree_b["branches"][branch]["leaves"]}
            only_a = ids_a - ids_b
            only_b = ids_b - ids_a
            if only_a:
                result["leaves_only_in_a"][branch] = [
                    l for l in tree_a["branches"][branch]["leaves"]
                    if l["id"] in only_a
                ]
            if only_b:
                result["leaves_only_in_b"][branch] = [
                    l for l in tree_b["branches"][branch]["leaves"]
                    if l["id"] in only_b
                ]
    return result

# --- CLI ---------------------------------------------------------------

def cmd_add(args):
    if len(args) < 2:
        print("Usage: --add <branch> <knowledge> [--source X] [--confidence 0.N]")
        sys.exit(1)
    branch = args[0]
    content = args[1]
    source = "session"
    confidence = 0.7
    for i, arg in enumerate(args):
        if arg == "--source" and i + 1 < len(args):
            source = args[i + 1]
        if arg == "--confidence" and i + 1 < len(args):
            confidence = float(args[i + 1])
    with tree_lock() as tree:
        leaf_id = add_knowledge(tree, branch, content, source, confidence)
    print(f"Added to [{branch}]: {content[:60]}...")
    print(f"   ID: {leaf_id} | Source: {source} | Confidence: {confidence}")
    print(f"   Root: {tree['root_hash'][:24]}...")

    # Auto-index for semantic search if index exists
    try:
        from knowledge_search import incremental_index, INDEX_FILE
        if os.path.exists(INDEX_FILE):
            if incremental_index(leaf_id, branch, content, source, confidence):
                print(f"   Indexed for semantic search.")
            else:
                print(f"   Search indexing failed -- run knowledge_search.py --reindex")
    except (ImportError, Exception):
        pass  # semantic search not set up yet, that's fine


def cmd_show(args):
    tree = load_tree()
    if args:
        branch = args[0]
        if branch not in tree["branches"]:
            print(f"Branch '{branch}' not found. Available: {list(tree['branches'].keys())}")
            return
        leaves = tree["branches"][branch]["leaves"]
        print(f"\nBranch: {branch} ({len(leaves)} leaves)")
        print(f"   Hash: {tree['branches'][branch]['hash'][:24]}...\n")
        for leaf in leaves:
            conf = leaf["confidence"]
            bar = "#" * int(conf * 10) + "." * (10 - int(conf * 10))
            print(f"   [{leaf['id']}] {leaf['content'][:70]}")
            print(f"            source: {leaf['source']} | confidence: [{bar}] {conf}")
            print(f"            created: {leaf['created']}")
            if leaf.get("promoted_to"):
                print(f"            -> promoted to: {leaf['promoted_to']}")
            print()
    else:
        print(f"\nKnowledge Tree")
        print(f"   Root: {tree['root_hash'][:24]}...")
        print(f"   Last updated: {tree['last_updated']}")
        print(f"   Instance: {tree.get('instance', 'primary')}\n")
        for name in sorted(tree["branches"].keys()):
            branch = tree["branches"][name]
            count = len(branch["leaves"])
            print(f"   {name:20s}  {count:3d} leaves  {branch['hash'][:16]}...")
        total = sum(len(b["leaves"]) for b in tree["branches"].values())
        print(f"\n   Total: {total} knowledge leaves across {len(tree['branches'])} branches")


def cmd_root():
    tree = load_tree()
    print(tree["root_hash"])


def cmd_diff(args):
    if not args:
        print("Usage: --diff <path_to_other_tree.json>")
        sys.exit(1)
    tree_a = load_tree()
    try:
        with open(args[0], "r") as f:
            tree_b = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading {args[0]}: {e}")
        sys.exit(1)
    result = diff_trees(tree_a, tree_b)
    if result["roots_match"]:
        print("Trees are identical.")
        return
    print("Trees diverge:\n")
    if result["branches_only_in_a"]:
        print(f"  Branches only in local:  {result['branches_only_in_a']}")
    if result["branches_only_in_b"]:
        print(f"  Branches only in remote: {result['branches_only_in_b']}")
    if result["branches_identical"]:
        print(f"  Identical branches:      {result['branches_identical']}")
    if result["branches_diverged"]:
        print(f"  Diverged branches:       {result['branches_diverged']}")
    for branch, leaves in result.get("leaves_only_in_a", {}).items():
        print(f"\n  [{branch}] Local has {len(leaves)} leaf(s) not in remote:")
        for l in leaves:
            print(f"    + {l['id']}: {l['content'][:60]}...")
    for branch, leaves in result.get("leaves_only_in_b", {}).items():
        print(f"\n  [{branch}] Remote has {len(leaves)} leaf(s) not in local:")
        for l in leaves:
            print(f"    + {l['id']}: {l['content'][:60]}...")


def cmd_export():
    tree = load_tree()
    print(json.dumps(tree, indent=2))


def cmd_prune(args):
    if len(args) < 2:
        print("Usage: --prune <branch> <leaf_id>")
        sys.exit(1)
    with tree_lock() as tree:
        if prune_leaf(tree, args[0], args[1]):
            print(f"Pruned leaf {args[1]} from [{args[0]}]")
            print(f"   New root: {tree['root_hash'][:24]}...")
        else:
            print(f"Leaf {args[1]} not found in [{args[0]}]")


def cmd_link(args):
    if len(args) < 3:
        print("Usage: --link <from_leaf_id> <to_leaf_id> <RELATION> [--note '...'] [--source '...']")
        sys.exit(1)
    from_leaf_id, to_leaf_id, relation = args[0], args[1], args[2]
    note, source = "", "session"
    for i, arg in enumerate(args):
        if arg == "--note" and i + 1 < len(args):
            note = args[i + 1]
        if arg == "--source" and i + 1 < len(args):
            source = args[i + 1]
    from knowledge_synapses import (
        load_synapses, save_synapses, add_synapse, find_leaf_in_tree,
    )
    tree = load_tree()
    br_a, _ = find_leaf_in_tree(tree, from_leaf_id)
    br_b, _ = find_leaf_in_tree(tree, to_leaf_id)
    if br_a is None:
        print(f"Error: leaf '{from_leaf_id}' not found in tree.")
        sys.exit(1)
    if br_b is None:
        print(f"Error: leaf '{to_leaf_id}' not found in tree.")
        sys.exit(1)
    synapses = load_synapses()
    synapse_id = add_synapse(synapses, from_leaf_id, to_leaf_id, relation, note, source)
    save_synapses(synapses)
    print(f"Synapse created: {from_leaf_id} --[{relation}]--> {to_leaf_id}")
    print(f"   ID: {synapse_id}")
    print(f"   Root: {synapses['root_hash'][:24]}...")


def cmd_links(args):
    if not args:
        print("Usage: --links <leaf_id>")
        sys.exit(1)
    leaf_id = args[0]
    from knowledge_synapses import load_synapses, get_synapses_for_leaf, find_leaf_in_tree
    tree = load_tree()
    synapses = load_synapses()
    matches = get_synapses_for_leaf(synapses, leaf_id)
    if not matches:
        print(f"No synapses found for leaf {leaf_id}.")
        return
    print(f"\nSynapses for leaf {leaf_id} ({len(matches)}):\n")
    for s in matches:
        if s["from_leaf"] == leaf_id:
            other_id = s["to_leaf"]
            direction = f"--[{s['relation']}]-->"
        else:
            other_id = s["from_leaf"]
            direction = f"<--[{s['relation']}]--"
        _, other_leaf = find_leaf_in_tree(tree, other_id)
        content_preview = other_leaf["content"][:60] if other_leaf else "(leaf not found)"
        print(f"   {direction} {other_id}: {content_preview}")
        if s["note"]:
            print(f"            note: {s['note']}")
    print()


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        cmd_show([])
    elif args[0] == "--add":
        cmd_add(args[1:])
    elif args[0] == "--show":
        cmd_show(args[1:])
    elif args[0] == "--root":
        cmd_root()
    elif args[0] == "--diff":
        cmd_diff(args[1:])
    elif args[0] == "--export":
        cmd_export()
    elif args[0] == "--prune":
        cmd_prune(args[1:])
    elif args[0] == "--link":
        cmd_link(args[1:])
    elif args[0] == "--links":
        cmd_links(args[1:])
    elif args[0] == "--assess":
        from belief_traversal import assess_belief
        if len(args) < 2:
            print("Usage: --assess <leaf_id>")
            sys.exit(1)
        tree = load_tree()
        result = assess_belief(args[1], tree=tree)
        print(f"\nBelief Assessment: {result['leaf_id']}")
        print(f"  Content:     {result['content']}")
        print(f"  Branch:      {result.get('branch', '?')}")
        print(f"  Net belief:  {result['net_confidence']:.2f} ({result['stance']})")
        print(f"  Reasoning:   {result['reasoning']}")
        print(f"  Support:     {result['support_count']} | Contradictions: {result['contradiction_count']}")
    elif args[0] == "--query-belief":
        from belief_traversal import query_belief
        if len(args) < 2:
            print("Usage: --query-belief <text>")
            sys.exit(1)
        query_text = " ".join(args[1:])
        results = query_belief(query_text)
        if not results:
            print("No results found.")
        for r in results:
            print(f"\n[{r['stance']}] {r['leaf_id']} ({r['branch']})")
            print(f"  {r['content']}")
            print(f"  Net belief: {r['net_confidence']:.2f} | {r['reasoning']}")
    elif args[0] == "--decay":
        from core.belief_decay import apply_decay_to_tree
        half_life = 180
        dry_run = False
        for i, arg in enumerate(args[1:]):
            if arg == "--half-life" and i + 2 < len(args):
                half_life = int(args[i + 2])
            if arg == "--dry-run":
                dry_run = True
        summary = apply_decay_to_tree(
            half_life_days=half_life, dry_run=dry_run
        )
        mode = "DRY RUN" if dry_run else "APPLIED"
        print(f"\nBelief Decay ({mode}, half-life={half_life}d)")
        print(f"   Leaves updated: {summary['updated']}/{summary['total']}")
        print(f"   Exempt (skipped): {summary['skipped']}")
        print(f"   Decay range: {summary['min_decay']:.4f} – {summary['max_decay']:.4f}")
        print(f"   Avg decay: {summary['avg_decay']:.4f}")
        if not dry_run and summary['updated'] > 0:
            tree = load_tree()
            print(f"   New root: {tree['root_hash'][:24]}...")
    elif args[0] == "--help":
        print(__doc__)
    else:
        print(f"Unknown command: {args[0]}")
        print("Use --help for usage.")
        sys.exit(1)
