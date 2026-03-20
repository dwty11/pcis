#!/usr/bin/env python3
"""
PCIS Demo Server
Serves the demo UI and API endpoints using demo_tree.json.
Run: python demo/server.py
Then open: http://localhost:5555
"""

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, request, send_file

app = Flask(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_DIR  = os.path.dirname(os.path.abspath(__file__))
CORE_DIR  = os.path.join(REPO_ROOT, "core")
DATA_DIR  = os.path.join(REPO_ROOT, "data")

DEMO_TREE_FILE       = os.path.join(DEMO_DIR, "demo_tree.json")
VALIDATION_FILE      = os.path.join(DEMO_DIR, "adversarial_validation_run.json")
REAL_TREE_FILE       = os.path.join(DATA_DIR, "tree.json")
VERIFY_SCRIPT        = os.path.join(CORE_DIR, "verify_memory.py")

# Add core to path so imports work
sys.path.insert(0, CORE_DIR)

TZ = timezone(timedelta(hours=0))  # UTC; adjust as needed


def load_tree(demo=True):
    """Load demo tree or real tree."""
    path = DEMO_TREE_FILE if demo else REAL_TREE_FILE
    with open(path) as f:
        return json.load(f)


def compute_merkle_root(tree):
    """Recompute root hash from current leaf hashes."""
    all_hashes = []
    for branch in sorted(tree["branches"].keys()):
        for leaf in tree["branches"][branch]["leaves"]:
            all_hashes.append(leaf["hash"])
    combined = "".join(sorted(all_hashes))
    return hashlib.sha256(combined.encode()).hexdigest()


# ── Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_file(os.path.join(DEMO_DIR, "index.html"))


@app.route("/api/boot")
def api_boot():
    """
    Boot integrity check.
    Recomputes Merkle root from demo_tree.json and verifies it matches stored root.
    This proves the knowledge tree has not been modified since last verification.
    """
    try:
        tree = load_tree(demo=True)
        stored_root = tree["root_hash"]
        computed_root = compute_merkle_root(tree)
        status = "CLEAN" if stored_root == computed_root else "CHANGED"

        # Build file manifest from core/ scripts
        tracked = [
            "knowledge_tree.py",
            "knowledge_prune.py",
            "knowledge_search.py",
            "verify_memory.py",
            "gardener.py",
        ]
        file_checks = []
        for fname in tracked:
            fpath = os.path.join(CORE_DIR, fname)
            if os.path.exists(fpath):
                with open(fpath, "rb") as f:
                    h = hashlib.sha256(f.read()).hexdigest()
                file_checks.append({"file": fname, "hash": h[:24], "status": "OK"})
            else:
                file_checks.append({"file": fname, "hash": None, "status": "MISSING"})

        return jsonify({
            "status": status,
            "merkle_root": stored_root[:24],
            "computed_root": computed_root[:24],
            "match": stored_root == computed_root,
            "timestamp": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "changed": 0 if status == "CLEAN" else 1,
            "missing": 0,
            "file_checks": file_checks,
        })
    except Exception as e:
        return jsonify({"status": "ERROR", "error": str(e)}), 500


@app.route("/api/tree")
def api_tree():
    """Return branch overview with leaf counts and entries."""
    tree = load_tree(demo=True)
    branches = []
    for name in sorted(tree["branches"].keys()):
        branch = tree["branches"][name]
        leaves = branch["leaves"]
        sample = [{
            "id": l["id"],
            "content": l["content"][:200],
            "confidence": l["confidence"],
            "source": l["source"],
            "created": l["created"],
            "hash": l["hash"][:24],
            "is_counter": l["content"].startswith("COUNTER:"),
        } for l in leaves[:5]]
        branches.append({
            "name": name,
            "leaf_count": len(leaves),
            "hash": branch["hash"][:24],
            "sample": sample,
            "all_leaves": [{
                "id": l["id"],
                "content": l["content"][:300],
                "confidence": l["confidence"],
                "source": l["source"],
                "created": l["created"],
                "hash": l["hash"][:24],
                "is_counter": l["content"].startswith("COUNTER:"),
            } for l in leaves],
        })

    total_leaves = sum(b["leaf_count"] for b in branches)
    return jsonify({
        "root_hash": tree["root_hash"][:24],
        "last_updated": tree["last_updated"],
        "branch_count": len(branches),
        "total_leaves": total_leaves,
        "branches": branches,
    })


@app.route("/api/query", methods=["POST"])
def api_query():
    """Keyword search across the knowledge tree. Returns top 3 matches."""
    data = request.get_json()
    query = data.get("query", "").lower().strip()
    if not query:
        return jsonify({"results": [], "query": ""})

    tree = load_tree(demo=True)
    keywords = query.split()
    scored = []
    for branch_name, branch in tree["branches"].items():
        for leaf in branch["leaves"]:
            content_lower = leaf["content"].lower()
            hits = sum(1 for kw in keywords if kw in content_lower)
            if hits > 0:
                scored.append({
                    "branch": branch_name,
                    "content": leaf["content"],
                    "confidence": leaf["confidence"],
                    "hash": leaf["hash"],
                    "source": leaf["source"],
                    "created": leaf["created"],
                    "id": leaf["id"],
                    "score": round(hits * leaf["confidence"], 3),
                })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return jsonify({"results": scored[:3], "query": query, "total_matches": len(scored)})


@app.route("/api/adversarial")
def api_adversarial():
    """Return COUNTER-tagged entries from the knowledge tree."""
    tree = load_tree(demo=True)
    counters = []
    for branch_name, branch in tree["branches"].items():
        for leaf in branch["leaves"]:
            if leaf["content"].startswith("COUNTER:"):
                content = leaf["content"]
                challenged_id = None
                if "[" in content and "]" in content:
                    challenged_id = content[content.index("[")+1:content.index("]")]
                original = None
                if challenged_id:
                    for bn, br in tree["branches"].items():
                        for ol in br["leaves"]:
                            if ol["id"] == challenged_id:
                                original = {"branch": bn, "content": ol["content"],
                                            "confidence": ol["confidence"], "id": ol["id"]}
                                break
                counters.append({
                    "branch": branch_name,
                    "counter_content": content,
                    "confidence": leaf["confidence"],
                    "source": leaf["source"],
                    "created": leaf["created"],
                    "id": leaf["id"],
                    "hash": leaf["hash"][:24],
                    "challenged_id": challenged_id,
                    "original": original,
                })
    counters.sort(key=lambda x: x["created"], reverse=True)
    return jsonify({"counters": counters[:5], "total_counters": len(counters)})


@app.route("/api/adversarial-validation")
def api_adversarial_validation():
    """Return external LLM adversarial validation run results."""
    if not os.path.exists(VALIDATION_FILE):
        return jsonify({"status": "not_run", "message": "Run adversarial_validator.py first"})
    with open(VALIDATION_FILE) as f:
        data = json.load(f)
    tree = load_tree(demo=True)
    for counter in data.get("counters", []):
        challenged_id = counter.get("challenged_id")
        counter["original_content"] = None
        if challenged_id:
            for branch in tree["branches"].values():
                for leaf in branch["leaves"]:
                    if leaf["id"] == challenged_id:
                        counter["original_content"] = leaf["content"]
                        break
    return jsonify(data)


@app.route("/api/status")
def api_status():
    """System health overview."""
    tree = load_tree(demo=True)
    total_leaves = sum(len(b["leaves"]) for b in tree["branches"].values())
    counter_count = sum(
        1 for b in tree["branches"].values()
        for l in b["leaves"] if l["content"].startswith("COUNTER:")
    )
    return jsonify({
        "tree_stats": {
            "total_leaves": total_leaves,
            "branches": len(tree["branches"]),
            "counter_leaves": counter_count,
            "root_hash": tree["root_hash"][:24],
        },
        "last_updated": tree["last_updated"],
        "instance": tree.get("instance", "pcis-demo"),
        "version": tree.get("version", 1),
        "demo_mode": True,
    })


if __name__ == "__main__":
    print(f"\n  PCIS Demo Server")
    print(f"  Tree: {DEMO_TREE_FILE}")
    print(f"  Open: http://localhost:5555\n")
    app.run(host="127.0.0.1", port=5555, debug=False)
