#!/usr/bin/env python3
"""
knowledge_synapses.py — Typed directed edges between knowledge leaves.

Turns the Merkle Knowledge Tree from a filing cabinet into a belief network.
Each synapse is a directed edge with a relation type, tamper-evident via SHA-256.

No external dependencies. Python 3.8+.
"""

import fcntl
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

BASE_DIR = os.environ.get("PCIS_BASE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TREE_FILE = os.path.join(BASE_DIR, "data", "tree.json")
SYNAPSES_FILE = os.path.join(BASE_DIR, "data", "synapses.json")

TZ_UTC = timezone.utc

VALID_RELATIONS = {"SUPPORTS", "CONTRADICTS", "REFINES", "DERIVES_FROM", "SUPERSEDES"}


def now_utc():
    return datetime.now(TZ_UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def hash_synapse(from_leaf, to_leaf, relation, created):
    data = f"{from_leaf}+{to_leaf}+{relation}+{created}"
    return hashlib.sha256(data.encode()).hexdigest()


def compute_synapses_root(synapses):
    hashes = sorted(s["hash"] for s in synapses.get("synapses", []))
    if not hashes:
        return hashlib.sha256(b"EMPTY_SYNAPSES").hexdigest()
    combined = "|".join(hashes)
    return hashlib.sha256(combined.encode()).hexdigest()


def load_synapses(path=None):
    path = path or SYNAPSES_FILE
    if os.path.exists(path):
        with open(path, "r") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                print(f"Error: synapses file is corrupted ({e}).")
                print(f"       Fix or remove {path} manually.")
                sys.exit(1)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
            return data
    return {
        "version": 1,
        "created": now_utc(),
        "last_updated": now_utc(),
        "root_hash": hashlib.sha256(b"EMPTY_SYNAPSES").hexdigest(),
        "synapses": [],
    }


def save_synapses(synapses, path=None):
    path = path or SYNAPSES_FILE
    synapses["last_updated"] = now_utc()
    synapses["root_hash"] = compute_synapses_root(synapses)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            json.dump(synapses, f, indent=2)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    os.replace(tmp, path)


def add_synapse(synapses, from_leaf, to_leaf, relation, note="", source="session",
                tree=None):
    if relation not in VALID_RELATIONS:
        raise ValueError(f"Invalid relation '{relation}'. Must be one of: {VALID_RELATIONS}")
    if note and len(note) > 500:
        raise ValueError("Note must be 500 characters or fewer.")
    created = now_utc()
    synapse_hash = hash_synapse(from_leaf, to_leaf, relation, created)
    synapse_id = str(uuid.uuid4())
    synapse = {
        "id": synapse_id,
        "from_leaf": from_leaf,
        "to_leaf": to_leaf,
        "relation": relation,
        "note": note,
        "source": source,
        "created": created,
        "hash": synapse_hash,
    }
    synapses["synapses"].append(synapse)

    # Bayesian belief update — lazy import to avoid circular dependency
    if tree is not None and relation in ("SUPPORTS", "CONTRADICTS"):
        try:
            from core.belief_updater import update_from_synapse
            update_from_synapse(synapse, tree)
        except Exception:
            pass  # updater is optional; don't break synapse creation

    return synapse_id


def get_synapses_for_leaf(synapses, leaf_id):
    return [
        s for s in synapses.get("synapses", [])
        if s["from_leaf"] == leaf_id or s["to_leaf"] == leaf_id
    ]


def verify_synapses(synapses):
    errors = []
    for i, s in enumerate(synapses.get("synapses", [])):
        expected = hash_synapse(s["from_leaf"], s["to_leaf"], s["relation"], s["created"])
        if s["hash"] != expected:
            errors.append(f"Synapse {s['id']}: hash mismatch (expected {expected[:16]}..., got {s['hash'][:16]}...)")
    expected_root = compute_synapses_root(synapses)
    if synapses.get("root_hash") != expected_root:
        errors.append(f"Root hash mismatch (expected {expected_root[:16]}..., got {synapses.get('root_hash', 'MISSING')[:16]}...)")
    return (len(errors) == 0, errors)


def find_leaf_in_tree(tree, leaf_id):
    """Find a leaf by ID across all branches. Returns (branch, leaf) or (None, None)."""
    for branch_name, branch in tree.get("branches", {}).items():
        for leaf in branch.get("leaves", []):
            if leaf["id"] == leaf_id:
                return branch_name, leaf
    return None, None
