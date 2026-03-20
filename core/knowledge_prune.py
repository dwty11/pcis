#!/usr/bin/env python3
"""
knowledge_prune.py — Knowledge Tree Pruning Protocol

Active forgetting for a knowledge tree. Biological memory prunes.
Digital memory should too. Without pruning, low-value noise accumulates
and degrades semantic search quality over time.

Usage:
    python3 knowledge_prune.py --review              # Interactive review of prune candidates
    python3 knowledge_prune.py --stale                # Show leaves older than 90 days, never refreshed
    python3 knowledge_prune.py --low-confidence 0.6   # Show leaves below confidence threshold
    python3 knowledge_prune.py --branch-health        # Check health metrics per branch
    python3 knowledge_prune.py --auto-flag             # Flag candidates, don't delete (safe)
    python3 knowledge_prune.py --execute               # Actually prune flagged leaves (requires --confirm)

Schedule: Quarterly review, or whenever tree exceeds 200 leaves.
Principle: A gardener, not a hoarder. Prune what no longer serves.

No external dependencies. Python 3.8+.
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone, timedelta

BASE_DIR = os.environ.get("PCIS_BASE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TREE_FILE = os.path.join(BASE_DIR, "data", "tree.json")
PRUNE_LOG = os.path.join(BASE_DIR, "data", "prune-log.json")
TZ_UTC = timezone.utc

try:
    from knowledge_tree import compute_root_hash
except ImportError:
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


def now_utc():
    return datetime.now(TZ_UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def days_since(date_str):
    """Calculate days since a date string."""
    try:
        for fmt in ["%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
            try:
                dt = datetime.strptime(date_str.replace(" UTC", "").replace(" UTC", ""), fmt.replace(" UTC", "").replace(" UTC", ""))
                now = datetime.now()
                return (now - dt).days
            except ValueError:
                continue
        return 0
    except Exception:
        return 0


def load_tree():
    if not os.path.exists(TREE_FILE):
        print("Knowledge tree not found.")
        sys.exit(1)
    with open(TREE_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error: knowledge tree is corrupted ({e}). Fix or remove {TREE_FILE} manually.")
            sys.exit(1)


def save_tree(tree):
    tree["last_updated"] = now_utc()
    tree["root_hash"] = compute_root_hash(tree)
    tmp = TREE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(tree, f, indent=2)
    os.replace(tmp, TREE_FILE)


def load_prune_log():
    if os.path.exists(PRUNE_LOG):
        with open(PRUNE_LOG, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError as e:
                print(f"Warning: prune log corrupted ({e}), starting fresh.")
                return {"sessions": [], "total_pruned": 0, "total_refreshed": 0}
    return {"sessions": [], "total_pruned": 0, "total_refreshed": 0}


def save_prune_log(log):
    os.makedirs(os.path.dirname(PRUNE_LOG), exist_ok=True)
    with open(PRUNE_LOG, "w") as f:
        json.dump(log, f, indent=2)


# --- Analysis Commands --------------------------------------------------

def cmd_stale(max_days=90):
    """Show leaves older than max_days that haven't been refreshed."""
    tree = load_tree()
    stale = []

    for branch_name, branch in tree.get("branches", {}).items():
        for leaf in branch.get("leaves", []):
            age = days_since(leaf.get("created", ""))
            if age >= max_days:
                stale.append({
                    "branch": branch_name,
                    "id": leaf["id"],
                    "content": leaf["content"],
                    "confidence": leaf.get("confidence", 0.7),
                    "age_days": age,
                    "source": leaf.get("source", ""),
                })

    if not stale:
        print(f"No leaves older than {max_days} days. Tree is fresh.")
        return

    stale.sort(key=lambda x: x["age_days"], reverse=True)
    print(f"\nStale leaves (older than {max_days} days):\n")
    for s in stale:
        print(f"  [{s['branch']}] {s['content'][:60]}...")
        print(f"    ID: {s['id']} | Age: {s['age_days']}d | Confidence: {s['confidence']} | Source: {s['source']}")
        print()

    print(f"Total: {len(stale)} stale leaves")


def cmd_low_confidence(threshold=0.6):
    """Show leaves below confidence threshold."""
    tree = load_tree()
    low = []

    for branch_name, branch in tree.get("branches", {}).items():
        for leaf in branch.get("leaves", []):
            conf = leaf.get("confidence", 0.7)
            if conf < threshold:
                low.append({
                    "branch": branch_name,
                    "id": leaf["id"],
                    "content": leaf["content"],
                    "confidence": conf,
                    "source": leaf.get("source", ""),
                    "age_days": days_since(leaf.get("created", "")),
                })

    if not low:
        print(f"No leaves below {threshold} confidence. Quality is high.")
        return

    low.sort(key=lambda x: x["confidence"])
    print(f"\nLow-confidence leaves (below {threshold}):\n")
    for l in low:
        print(f"  [{l['branch']}] {l['content'][:60]}...")
        print(f"    ID: {l['id']} | Confidence: {l['confidence']} | Age: {l['age_days']}d | Source: {l['source']}")
        print()

    print(f"Total: {len(low)} low-confidence leaves")


def cmd_branch_health():
    """Check health metrics per branch. Healthy branches have mixed confidence."""
    tree = load_tree()

    print("\nBranch Health Report:\n")

    for branch_name in sorted(tree.get("branches", {}).keys()):
        branch = tree["branches"][branch_name]
        leaves = branch.get("leaves", [])

        if not leaves:
            print(f"  {branch_name:20s}  empty")
            continue

        confidences = [l.get("confidence", 0.7) for l in leaves]
        ages = [days_since(l.get("created", "")) for l in leaves]

        avg_conf = sum(confidences) / len(confidences)
        min_conf = min(confidences)
        max_conf = max(confidences)
        conf_spread = max_conf - min_conf
        avg_age = sum(ages) / len(ages)
        oldest = max(ages)

        warnings = []
        if avg_conf > 0.85:
            warnings.append("HIGH AVG CONFIDENCE -- may indicate echo chamber")
        if conf_spread < 0.1 and len(leaves) > 3:
            warnings.append("LOW SPREAD -- everything at same confidence, suspicious")
        if oldest > 90 and len(leaves) > 5:
            warnings.append(f"OLDEST LEAF: {oldest}d -- consider refresh")

        status = "healthy" if not warnings else "review"

        print(f"  {branch_name:20s}  {len(leaves):3d} leaves | "
              f"conf: {avg_conf:.2f} (range {min_conf:.1f}-{max_conf:.1f}) | "
              f"avg age: {avg_age:.0f}d | status: {status}")

        for w in warnings:
            print(f"    WARNING: {w}")

    print()


def cmd_auto_flag():
    """Flag prune candidates without deleting anything."""
    tree = load_tree()
    candidates = _get_candidates(tree)

    if not candidates:
        print("No prune candidates found. Tree is clean.")
        return

    print(f"\nPrune candidates ({len(candidates)}):\n")
    for c in candidates:
        print(f"  [{c['branch']}] {c['content']}...")
        print(f"    ID: {c['id']} | Reasons: {', '.join(c['reasons'])}")
        print()

    print(f"To prune: python3 knowledge_tree.py --prune <branch> <leaf_id>")
    print(f"Or run knowledge_prune.py --review for interactive mode")


def _get_candidates(tree):
    """Return all auto-flag candidates from the tree."""
    candidates = []
    for branch_name, branch in tree.get("branches", {}).items():
        for leaf in branch.get("leaves", []):
            reasons = []
            conf = leaf.get("confidence", 0.7)
            age = days_since(leaf.get("created", ""))
            if conf < 0.5:
                reasons.append(f"very low confidence ({conf})")
            if age > 180 and conf < 0.7:
                reasons.append(f"old ({age}d) + low confidence ({conf})")
            if leaf.get("content", "").strip() == "":
                reasons.append("empty content")
            if reasons:
                candidates.append({
                    "branch": branch_name,
                    "id": leaf["id"],
                    "content": leaf["content"][:60],
                    "confidence": conf,
                    "age_days": age,
                    "reasons": reasons,
                })
    return candidates


def cmd_execute(yes=False, dry_run=False):
    """Prune all auto-flagged candidates. Use --yes to confirm, --dry-run to preview."""
    tree = load_tree()
    candidates = _get_candidates(tree)

    if not candidates:
        print("No prune candidates found. Tree is clean.")
        return

    print(f"\nPrune candidates ({len(candidates)}):\n")
    for c in candidates:
        print(f"  [{c['branch']}] {c['content']}...")
        print(f"    ID: {c['id']} | Reasons: {', '.join(c['reasons'])}")
        print()

    if dry_run:
        print(f"Dry run -- {len(candidates)} leaf(s) would be pruned. Pass --yes to execute.")
        return

    if not yes:
        print(f"Pass --yes to confirm pruning {len(candidates)} leaf(s).")
        return

    pruned = 0
    for c in candidates:
        branch = tree["branches"].get(c["branch"])
        if branch:
            before = len(branch["leaves"])
            branch["leaves"] = [l for l in branch["leaves"] if l["id"] != c["id"]]
            if len(branch["leaves"]) < before:
                import hashlib as _hashlib
                leaf_hashes = [l["hash"] for l in branch["leaves"]]
                if leaf_hashes:
                    combined = "|".join(sorted(leaf_hashes))
                    branch["hash"] = _hashlib.sha256(combined.encode()).hexdigest()
                else:
                    branch["hash"] = _hashlib.sha256(b"EMPTY_BRANCH").hexdigest()
                pruned += 1

    save_tree(tree)

    log = load_prune_log()
    log["sessions"].append({
        "timestamp": now_utc(),
        "pruned": pruned,
        "refreshed": 0,
        "kept": 0,
        "mode": "execute",
        "total_leaves_after": sum(len(b.get("leaves", [])) for b in tree.get("branches", {}).values()),
    })
    log["total_pruned"] += pruned
    save_prune_log(log)

    print(f"Pruned {pruned} leaf(s). New root: {tree['root_hash'][:24]}...")


def cmd_review(yes=False, dry_run=False):
    """Interactive review -- show each candidate and ask keep/prune/refresh.
    Pass --yes to auto-prune all candidates without prompts.
    Pass --dry-run to preview without making changes.
    """
    tree = load_tree()
    total_leaves = sum(len(b.get("leaves", [])) for b in tree.get("branches", {}).values())

    print(f"\nKnowledge Tree Pruning Review")
    print(f"Total leaves: {total_leaves}")
    if dry_run:
        print(f"(dry run -- no changes will be made)")
    elif yes:
        print(f"(--yes: all candidates will be auto-pruned)")
    print(f"{'=' * 50}\n")

    actions = {"kept": 0, "pruned": 0, "refreshed": 0}

    for branch_name in sorted(tree.get("branches", {}).keys()):
        branch = tree["branches"][branch_name]
        leaves_to_remove = []

        for leaf in branch.get("leaves", []):
            conf = leaf.get("confidence", 0.7)
            age = days_since(leaf.get("created", ""))

            if conf >= 0.7 and age < 90:
                continue

            print(f"  [{branch_name}] {leaf['content']}")
            print(f"  Confidence: {conf} | Age: {age}d | Source: {leaf.get('source', '?')}")
            print(f"  ID: {leaf['id']}")

            if dry_run:
                print("  -> would be reviewed (dry run)\n")
                continue

            if yes:
                action = 'p'
                print("  -> auto-pruning (--yes)\n")
            else:
                action = input("  Action -- [k]eep / [p]rune / [r]efresh confidence / [s]kip: ").strip().lower()

            if action == 'p':
                leaves_to_remove.append(leaf['id'])
                actions["pruned"] += 1
                if not yes:
                    print("  -> PRUNED\n")
            elif action == 'r' and not yes:
                new_conf = input("  New confidence (0.0-1.0): ").strip()
                try:
                    leaf["confidence"] = float(new_conf)
                    leaf["last_refreshed"] = now_utc()
                    actions["refreshed"] += 1
                    print(f"  -> REFRESHED to {new_conf}\n")
                except ValueError:
                    print("  -> Invalid, skipped\n")
            elif action == 'k':
                actions["kept"] += 1
                if not yes:
                    print("  -> KEPT\n")
            else:
                if not yes:
                    print("  -> SKIPPED\n")

        if leaves_to_remove:
            branch["leaves"] = [l for l in branch["leaves"] if l["id"] not in leaves_to_remove]

    if dry_run:
        print(f"\nDry run complete. No changes made.")
        return

    if actions["pruned"] > 0 or actions["refreshed"] > 0:
        save_tree(tree)

        log = load_prune_log()
        log["sessions"].append({
            "timestamp": now_utc(),
            "pruned": actions["pruned"],
            "refreshed": actions["refreshed"],
            "kept": actions["kept"],
            "total_leaves_after": sum(len(b.get("leaves", [])) for b in tree.get("branches", {}).values()),
        })
        log["total_pruned"] += actions["pruned"]
        log["total_refreshed"] += actions["refreshed"]
        save_prune_log(log)

    print(f"\nSession complete:")
    print(f"  Kept: {actions['kept']} | Pruned: {actions['pruned']} | Refreshed: {actions['refreshed']}")
    print(f"  Tree now has {sum(len(b.get('leaves', [])) for b in tree.get('branches', {}).values())} leaves")


# --- Entry Point --------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]

    yes = "--yes" in args
    dry_run = "--dry-run" in args
    positional = [a for a in args if a not in ("--yes", "--dry-run")]

    if not positional or "--help" in positional:
        print(__doc__)
    elif positional[0] == "--stale":
        days = int(positional[1]) if len(positional) > 1 else 90
        cmd_stale(days)
    elif positional[0] == "--low-confidence":
        threshold = float(positional[1]) if len(positional) > 1 else 0.6
        cmd_low_confidence(threshold)
    elif positional[0] == "--branch-health":
        cmd_branch_health()
    elif positional[0] == "--auto-flag":
        cmd_auto_flag()
    elif positional[0] == "--execute":
        cmd_execute(yes=yes, dry_run=dry_run)
    elif positional[0] == "--review":
        cmd_review(yes=yes, dry_run=dry_run)
    else:
        print(f"Unknown command: {positional[0]}")
        print("Use --help for usage.")
