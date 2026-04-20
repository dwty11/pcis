#!/usr/bin/env python3
"""
gardener_connections.py — Proactive synapse discovery between knowledge leaves.

Scans pairs of leaves across branches, uses a local LLM to detect meaningful
relationships (SUPPORTS, CONTRADICTS, REFINES, DERIVES_FROM), writes synapses.

This is the mechanism that makes the graph a brain, not a filing cabinet.

Usage:
    python3 gardener_connections.py [--limit N] [--dry-run] [--cross-branch-only]

Environment variables:
    PCIS_BASE_DIR       — repo root (required for tree/synapse paths)
    PCIS_OLLAMA_URL     — LLM endpoint (default: http://localhost:11434)
    PCIS_LLM_MODEL      — model name (default: qwen3.5:9b)
"""

import argparse
import hashlib
import json
import logging
import os
import random
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from itertools import combinations

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pcis.gardener_connections")

# Ensure core/ is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from knowledge_tree import TREE_FILE, load_tree
from knowledge_synapses import (
    SYNAPSES_FILE,
    load_synapses,
    save_synapses,
)

BASE_DIR = os.environ.get(
    "PCIS_BASE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."),
)
LOG_FILE = os.path.join(BASE_DIR, "data", "gardener-connections.log")
SCANNED_FILE = os.path.join(BASE_DIR, "data", "gardener-connections-scanned.json")
STATS_FILE = os.path.join(BASE_DIR, "data", "gardener-connections-stats.log")

OLLAMA_URL = os.environ.get("PCIS_OLLAMA_URL", "http://localhost:11434") + "/api/chat"
OLLAMA_MODEL = os.environ.get("PCIS_LLM_MODEL", "qwen3.5:9b")

# Branches to skip — standing orders, not beliefs
SKIP_BRANCHES = {"constraints", "rules", "state"}

# Max pairs to evaluate per run (cost control)
DEFAULT_LIMIT = 20


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def append_log(msg):
    """Append a timestamped line to the connections log."""
    ts = now_utc()
    line = f"[{ts}] {msg}"
    log.info(msg)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def load_scanned():
    if os.path.exists(SCANNED_FILE):
        with open(SCANNED_FILE) as f:
            return set(json.load(f))
    return set()


def save_scanned(scanned):
    os.makedirs(os.path.dirname(SCANNED_FILE), exist_ok=True)
    with open(SCANNED_FILE, "w") as f:
        json.dump(list(scanned), f)


def pair_key(id1, id2):
    return "-".join(sorted([id1, id2]))


def existing_synapse_pairs(synapses_data):
    pairs = set()
    for s in synapses_data.get("synapses", []):
        fr = s.get("from_leaf", s.get("from", ""))
        to = s.get("to_leaf", s.get("to", ""))
        if fr and to:
            pairs.add(pair_key(fr, to))
    return pairs


def get_all_leaves(tree):
    leaves = []
    for branch, val in tree.get("branches", {}).items():
        if branch in SKIP_BRANCHES:
            continue
        branch_leaves = val.get("leaves", []) if isinstance(val, dict) else []
        for leaf in branch_leaves:
            content = leaf.get("content", "")
            if len(content) < 40:
                continue
            if content.strip() in ("COUNTER:", "SYNAPSE:"):
                continue
            leaves.append(
                {
                    "id": leaf.get("id", ""),
                    "branch": branch,
                    "content": content[:200],
                    "confidence": leaf.get("confidence", 0.8),
                    "source": leaf.get("source", ""),
                }
            )
    return leaves


def ask_ollama(prompt):
    """Send a prompt to the configured LLM and return the response text."""
    payload = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 200},
        }
    ).encode()

    req = urllib.request.Request(OLLAMA_URL, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
            return data.get("message", {}).get("content", "").strip()
    except Exception as e:
        log.warning("LLM error: %s", e)
        return ""


def detect_relation(leaf_a, leaf_b):
    """Ask the LLM whether two leaves are meaningfully related."""
    prompt = f"""You are analyzing two knowledge beliefs from an AI agent's knowledge tree.

Belief A [{leaf_a['branch']}]:
{leaf_a['content']}

Belief B [{leaf_b['branch']}]:
{leaf_b['content']}

Do these two beliefs have a meaningful intellectual connection?

If YES, respond with EXACTLY this format (nothing else):
RELATION: <type>
FROM: <A or B>
TO: <A or B>
NOTE: <one sentence explaining the specific connection>
SCORE: <1-5 integer>

Where type is one of: SUPPORTS, CONTRADICTS, REFINES, DERIVES_FROM

If NO meaningful connection, respond with exactly:
NO_CONNECTION

Be strict. Only flag genuine intellectual relationships, not superficial topic overlap."""

    response = ask_ollama(prompt)
    if not response or "NO_CONNECTION" in response:
        return None

    lines_dict = {}
    for line in response.strip().split("\n"):
        if ":" in line:
            key = line.split(":")[0].strip()
            val = ":".join(line.split(":")[1:]).strip()
            lines_dict[key] = val

    relation = lines_dict.get("RELATION", "").strip().upper()
    direction = lines_dict.get("FROM", "A").strip().upper()
    note = lines_dict.get("NOTE", "").strip()
    try:
        score = int(lines_dict.get("SCORE", "3").strip()[0])
    except (ValueError, IndexError):
        score = 3

    if relation not in ("SUPPORTS", "CONTRADICTS", "REFINES", "DERIVES_FROM"):
        return None
    if not note:
        return None

    if direction == "A":
        from_leaf, to_leaf = leaf_a["id"], leaf_b["id"]
    else:
        from_leaf, to_leaf = leaf_b["id"], leaf_a["id"]

    return {
        "from_leaf": from_leaf,
        "to_leaf": to_leaf,
        "relation": relation,
        "note": note,
        "score": score,
    }


def add_synapse_record(synapses_data, from_leaf, to_leaf, relation, note):
    """Append a new synapse to the synapses data structure."""
    created = now_utc()
    h = hashlib.sha256(f"{from_leaf}+{to_leaf}+{relation}+{created}".encode()).hexdigest()
    synapse = {
        "id": str(uuid.uuid4()),
        "from_leaf": from_leaf,
        "to_leaf": to_leaf,
        "relation": relation,
        "note": note,
        "source": "gardener-connections",
        "created": created,
        "hash": h,
    }
    synapses_data.setdefault("synapses", []).append(synapse)
    return synapse


def find_synapse_by_pair(synapses_data, id1, id2):
    """Find existing synapse for a leaf pair (direction-agnostic)."""
    key = pair_key(id1, id2)
    for s in synapses_data.get("synapses", []):
        fr = s.get("from_leaf", s.get("from", ""))
        to = s.get("to_leaf", s.get("to", ""))
        if fr and to and pair_key(fr, to) == key:
            return s
    return None


def update_synapse(synapse, relation, note):
    """Update an existing synapse in place."""
    created = now_utc()
    synapse["relation"] = relation
    synapse["note"] = note
    synapse["created"] = created
    synapse["hash"] = hashlib.sha256(
        f"{synapse['from_leaf']}+{synapse['to_leaf']}+{relation}+{created}".encode()
    ).hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Proactive synapse discovery")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help="Max pairs to evaluate this run")
    parser.add_argument("--dry-run", action="store_true",
                        help="Detect but don't write synapses")
    parser.add_argument("--cross-branch-only", action="store_true",
                        help="Only evaluate pairs from different branches")
    args = parser.parse_args()

    append_log(f"gardener_connections starting -- limit={args.limit}, dry_run={args.dry_run}")

    tree = load_tree()
    synapses_data = load_synapses()
    scanned = load_scanned()
    existing_pairs = existing_synapse_pairs(synapses_data)

    leaves = get_all_leaves(tree)
    append_log(f"Loaded {len(leaves)} eligible leaves from {len(set(l['branch'] for l in leaves))} branches")

    candidates = []
    for la, lb in combinations(leaves, 2):
        key = pair_key(la["id"], lb["id"])
        if key in scanned:
            continue
        if key in existing_pairs:
            scanned.add(key)
            continue
        cross = la["branch"] != lb["branch"]
        if args.cross_branch_only and not cross:
            continue
        score = (2 if cross else 1) + la["confidence"] + lb["confidence"]
        candidates.append((score, key, la, lb))

    candidates.sort(key=lambda x: -x[0])
    pool = candidates[: args.limit * 3]
    random.shuffle(pool)
    selected = pool[: args.limit]

    append_log(f"Evaluating {len(selected)} pairs ({len(candidates)} candidates total)")

    found = 0
    updated = 0
    filtered = 0
    branch_pair_counts = {}

    for _score, key, la, lb in selected:
        scanned.add(key)
        result = detect_relation(la, lb)
        if not result:
            continue

        if result["score"] < 3:
            filtered += 1
            append_log(f"  Filtered (score={result['score']}): {result['note'][:60]}")
            continue

        bp = f"{la['branch']} -> {lb['branch']}"
        branch_pair_counts[bp] = branch_pair_counts.get(bp, 0) + 1

        existing = find_synapse_by_pair(synapses_data, result["from_leaf"], result["to_leaf"])

        if existing:
            updated += 1
            append_log(f"SYNAPSE UPDATED [{bp}] [{result['relation']}]: {result['note'][:80]}")
            if not args.dry_run:
                update_synapse(existing, result["relation"], result["note"])
        else:
            found += 1
            append_log(f"SYNAPSE NEW [{bp}] [{result['relation']}]: {result['note'][:80]}")
            if not args.dry_run:
                add_synapse_record(
                    synapses_data,
                    result["from_leaf"],
                    result["to_leaf"],
                    result["relation"],
                    result["note"],
                )

    if not args.dry_run:
        save_synapses(synapses_data)
        save_scanned(scanned)
        append_log(
            f"Done. {found} new, {updated} updated, {filtered} filtered. "
            f"Total: {len(synapses_data.get('synapses', []))}"
        )
    else:
        save_scanned(scanned)
        append_log(f"Dry run done. {found} new, {updated} updates, {filtered} filtered (not written).")

    # Stats summary
    top_bp = max(branch_pair_counts, key=branch_pair_counts.get) if branch_pair_counts else "none"
    os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
    stats_line = (
        f"{now_utc()} | pairs_evaluated={len(selected)} | "
        f"synapses_written={found} | total_synapses={len(synapses_data.get('synapses', []))} | "
        f"top_branch_pair={top_bp}"
    )
    with open(STATS_FILE, "a") as f:
        f.write(stats_line + "\n")
    append_log(f"Stats: {stats_line}")


if __name__ == "__main__":
    main()
