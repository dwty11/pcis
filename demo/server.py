#!/usr/bin/env python3
"""
PCIS Demo Server
Self-contained demo: uses demo_tree.json for all endpoints.
Boot integrity check hashes the demo's own files — no external workspace required.
"""

import hashlib
import json
import os
import re
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, request, send_file

app = Flask(__name__)

DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
DEMO_TREE_FILE = os.path.join(DEMO_DIR, "demo_tree.json")
TZ_UTC = timezone.utc

# Files the demo hashes on boot (its own files)
DEMO_TRACKED_FILES = [
    "server.py",
    "demo_tree.json",
    "index.html",
]


def load_tree():
    with open(DEMO_TREE_FILE, "r") as f:
        return json.load(f)


@app.route("/")
def index():
    return send_file("index.html")


@app.route("/api/boot")
def api_boot():
    """Hash the demo's own files and verify the tree root. Fully self-contained."""
    try:
        tree = load_tree()
        file_checks = []
        all_ok = True

        for fname in DEMO_TRACKED_FILES:
            fpath = os.path.join(DEMO_DIR, fname)
            if os.path.exists(fpath):
                with open(fpath, "rb") as f:
                    h = hashlib.sha256(f.read()).hexdigest()
                file_checks.append({"file": fname, "hash": h[:24], "status": "OK"})
            else:
                file_checks.append({"file": fname, "hash": None, "status": "MISSING"})
                all_ok = False

        status = "CLEAN" if all_ok else "MISSING"

        return jsonify({
            "status": status,
            "merkle_root": tree["root_hash"],
            "timestamp": datetime.now(TZ_UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "changed": 0,
            "missing": 0 if all_ok else sum(1 for f in file_checks if f["status"] == "MISSING"),
            "file_checks": file_checks,
        })
    except Exception as e:
        return jsonify({"status": "ERROR", "error": str(e)}), 500


@app.route("/api/tree")
def api_tree():
    """Return branch overview with leaf counts and sample entries."""
    tree = load_tree()
    branches = []
    for name in sorted(tree["branches"].keys()):
        branch = tree["branches"][name]
        leaves = branch["leaves"]
        sample = []
        for leaf in leaves[:5]:
            sample.append({
                "id": leaf["id"],
                "content": leaf["content"][:200],
                "confidence": leaf["confidence"],
                "source": leaf["source"],
                "created": leaf["created"],
                "hash": leaf["hash"][:24],
                "is_counter": leaf["content"].startswith("COUNTER:"),
            })
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

    tree = load_tree()
    keywords = query.split()

    scored = []
    for branch_name, branch in tree["branches"].items():
        for leaf in branch["leaves"]:
            content_lower = leaf["content"].lower()
            source_lower = leaf["source"].lower()
            hits = sum(1 for kw in keywords if kw in content_lower or kw in source_lower)
            if hits > 0:
                score = hits * leaf["confidence"]
                scored.append({
                    "branch": branch_name,
                    "content": leaf["content"],
                    "confidence": leaf["confidence"],
                    "hash": leaf["hash"],
                    "source": leaf["source"],
                    "created": leaf["created"],
                    "id": leaf["id"],
                    "score": round(score, 3),
                })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return jsonify({"results": scored[:3], "query": query, "total_matches": len(scored)})


@app.route("/api/adversarial")
def api_adversarial():
    """Return COUNTER-tagged entries from the knowledge tree."""
    tree = load_tree()
    counters = []
    for branch_name, branch in tree["branches"].items():
        for leaf in branch["leaves"]:
            if leaf["content"].startswith("COUNTER:"):
                content = leaf["content"]
                challenged_id = None
                if "[" in content and "]" in content:
                    start = content.index("[") + 1
                    end = content.index("]")
                    challenged_id = content[start:end]

                original = None
                if challenged_id:
                    for bn, br in tree["branches"].items():
                        for ol in br["leaves"]:
                            if ol["id"] == challenged_id:
                                original = {
                                    "branch": bn,
                                    "content": ol["content"],
                                    "confidence": ol["confidence"],
                                    "id": ol["id"],
                                }
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


@app.route("/api/gigachat-validation")
def api_gigachat_validation():
    """Return GigaChat adversarial validation run results."""
    validation_file = os.path.join(DEMO_DIR, "gigachat_validation_run.json")
    if not os.path.exists(validation_file):
        return jsonify({"status": "not_run", "message": "Run adversarial_validator.py first"})
    with open(validation_file, "r") as f:
        data = json.load(f)
    tree = load_tree()
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
    tree = load_tree()

    total_leaves = sum(len(b["leaves"]) for b in tree["branches"].values())
    branch_count = len(tree["branches"])
    counter_count = sum(
        1 for b in tree["branches"].values()
        for l in b["leaves"]
        if l["content"].startswith("COUNTER:")
    )

    return jsonify({
        "tree_stats": {
            "total_leaves": total_leaves,
            "branches": branch_count,
            "counter_leaves": counter_count,
            "root_hash": tree["root_hash"][:24],
        },
        "last_updated": tree["last_updated"],
        "last_integrity_check": datetime.now(TZ_UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "last_gardener_run": None,
        "instance": tree.get("instance", "pcis-demo"),
        "version": tree.get("version", 1),
        "demo_mode": True,
    })


if __name__ == "__main__":
    print(f"\n  PCIS Demo Server")
    print(f"  Tree: {DEMO_TREE_FILE}")
    print(f"  http://localhost:5555\n")
    app.run(host="127.0.0.1", port=5555, debug=False)
