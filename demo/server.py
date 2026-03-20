#!/usr/bin/env python3
"""
PCIS Demo Server — VP-level presentation backend
DEMO_MODE=True: uses demo_tree.json (safe enterprise data)
Boot endpoint always runs real verify_memory.py (integrity proof point)
"""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, request, send_file

app = Flask(__name__)

# ── Demo mode: use demo_tree.json for tree/query/adversarial ──
DEMO_MODE = True

WORKSPACE = os.path.expanduser("BASE_DIR")
DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
DEMO_TREE_FILE = os.path.join(DEMO_DIR, "demo_tree.json")
REAL_TREE_FILE = os.path.join(WORKSPACE, ".agent-knowledge-tree.json")
VERIFY_SCRIPT = os.path.join(WORKSPACE, "verify_memory.py")
GARDENER_LOG = os.path.join(WORKSPACE, "memory", "gardener-log.md")
TZ_MOSCOW = timezone(timedelta(hours=3))


def sanitize_path(text):
    """Strip real system paths from any string before it reaches the frontend."""
    text = text.replace(WORKSPACE, "/secure/ai-memory/workspace")
    text = text.replace(os.path.expanduser("~"), "/secure/ai-memory")
    return text


def load_tree():
    """Load demo tree in demo mode, real tree otherwise."""
    tree_file = DEMO_TREE_FILE if DEMO_MODE else REAL_TREE_FILE
    with open(tree_file, "r") as f:
        return json.load(f)


@app.route("/")
def index():
    return send_file("index.html")


@app.route("/api/boot")
def api_boot():
    """Run verify_memory.py --status and return integrity state."""
    try:
        result = subprocess.run(
            [sys.executable, VERIFY_SCRIPT, "--status"],
            capture_output=True, text=True, timeout=30,
            cwd=WORKSPACE
        )
        output = result.stdout.strip()

        if output == "CLEAN":
            status = "CLEAN"
            changed = 0
            missing = 0
        elif output.startswith("CHANGED"):
            status = "CHANGED"
            parts = output.split()
            changed = int(parts[0].split(":")[1]) if ":" in parts[0] else 0
            missing = int(parts[1].split(":")[1]) if len(parts) > 1 and ":" in parts[1] else 0
        elif output == "NO_MANIFEST":
            status = "MISSING"
            changed = 0
            missing = 0
        else:
            status = "UNKNOWN"
            changed = 0
            missing = 0

        tree = load_tree()

        # Get tracked files for the animation
        tracked_files = [
            "IDENTITY.md", "SOUL.md", "AGENTS.md", "PREFLIGHT.md",
            "MEMORY-CORE.md", "MEMORY-PROJECTS.md", "MEMORY-SYSTEM.md",
            "MEMORY-LESSONS.md", "CONTEXT-LOADER.md", "verify_memory.py",
            "gardener.py", "knowledge_tree.py", "model_agnosticity_monitor.py",
        ]
        file_checks = []
        for fname in tracked_files:
            fpath = os.path.join(WORKSPACE, fname)
            if os.path.exists(fpath):
                with open(fpath, "rb") as f:
                    h = hashlib.sha256(f.read()).hexdigest()
                file_checks.append({"file": fname, "hash": h[:24], "status": "OK"})
            else:
                file_checks.append({"file": fname, "hash": None, "status": "MISSING"})

        return jsonify({
            "status": status,
            "merkle_root": tree["root_hash"],
            "timestamp": datetime.now(TZ_MOSCOW).strftime("%Y-%m-%d %H:%M:%S GMT+3"),
            "changed": changed,
            "missing": missing,
            "file_checks": file_checks,
        })
    except Exception as e:
        return jsonify({"status": "ERROR", "error": sanitize_path(str(e))}), 500


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
            # Score: count keyword hits, weight by confidence
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
    results = scored[:3]

    return jsonify({"results": results, "query": query, "total_matches": len(scored)})


@app.route("/api/adversarial")
def api_adversarial():
    """Return the last COUNTER-tagged entries from the knowledge tree."""
    tree = load_tree()
    counters = []
    for branch_name, branch in tree["branches"].items():
        for leaf in branch["leaves"]:
            if leaf["content"].startswith("COUNTER:"):
                # Parse the counter: extract the challenged leaf ID
                content = leaf["content"]
                challenged_id = None
                if "[" in content and "]" in content:
                    start = content.index("[") + 1
                    end = content.index("]")
                    challenged_id = content[start:end]

                # Find the original leaf that was challenged
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

    # Sort by date descending, take last 5
    counters.sort(key=lambda x: x["created"], reverse=True)
    return jsonify({"counters": counters[:5], "total_counters": len(counters)})


@app.route("/api/adversarial-validation")
def api_adversarial_validation():
    """Return external LLM adversarial validation run results."""
    validation_file = os.path.join(DEMO_DIR, "adversarial_validation_run.json")
    if not os.path.exists(validation_file):
        return jsonify({"status": "not_run", "message": "Run adversarial_validator.py first"})
    with open(validation_file, "r") as f:
        data = json.load(f)
    # Attach original claim content for each counter
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

    # Check gardener log for last run
    last_gardener = None
    if os.path.exists(GARDENER_LOG):
        with open(GARDENER_LOG, "r") as f:
            content = f.read()
        # Find last "Gardening Session" timestamp
        import re
        sessions = re.findall(r"Gardening Session — (.+?)(?:\s+\[)", content)
        if sessions:
            last_gardener = sessions[-1]

    # Last integrity check from manifest
    manifest_path = os.path.expanduser("~/.agent-integrity/.agent-manifest.json")
    last_integrity = None
    if os.path.exists(manifest_path):
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
        last_integrity = manifest.get("last_verified")

    return jsonify({
        "tree_stats": {
            "total_leaves": total_leaves,
            "branches": branch_count,
            "counter_leaves": counter_count,
            "root_hash": tree["root_hash"][:24],
        },
        "last_updated": tree["last_updated"],
        "last_integrity_check": last_integrity,
        "last_gardener_run": last_gardener,
        "instance": tree.get("instance", "primary"),
        "version": tree.get("version", 1),
        "demo_mode": DEMO_MODE,
    })


if __name__ == "__main__":
    mode = "DEMO (demo_tree.json)" if DEMO_MODE else "LIVE (real tree)"
    tree_path = DEMO_TREE_FILE if DEMO_MODE else REAL_TREE_FILE
    print(f"\n  PCIS Demo Server — {mode}")
    print(f"  Workspace: {WORKSPACE}")
    print(f"  Tree file: {tree_path}")
    print(f"  http://localhost:5555\n")
    app.run(host="127.0.0.1", port=5555, debug=False)

