#!/usr/bin/env python3
"""
PCIS Demo Server
Self-contained demo: uses demo_tree.json for all endpoints.
Boot integrity check hashes the demo's own files — no external workspace required.
"""

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, request, send_file

# Point knowledge_search at the demo tree before importing it.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import core.knowledge_search as knowledge_search
from core.knowledge_tree import verify_tree_integrity, add_knowledge, compute_root_hash

try:
    from core.belief_traversal import query_belief as _query_belief, assess_belief as _assess_belief
    _belief_available = True
except ImportError:
    _belief_available = False

logger = logging.getLogger(__name__)

app = Flask(__name__)

DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
DEMO_TREE_FILE = os.path.join(DEMO_DIR, "demo_tree.json")

# Override knowledge_search paths to use the demo tree and its own index.
knowledge_search.TREE_FILE = DEMO_TREE_FILE
knowledge_search.INDEX_FILE = os.path.join(DEMO_DIR, "demo_search_index.json")
TZ_UTC = timezone.utc

# demo_mode=True uses demo_tree.json; False uses data/tree.json
def _load_demo_mode():
    config_path = os.path.join(DEMO_DIR, "config.json")
    try:
        with open(config_path, "r") as f:
            return json.load(f).get("demo_mode", True)
    except (FileNotFoundError, json.JSONDecodeError):
        return True

DEMO_MODE = _load_demo_mode()

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


@app.route("/sokrat.html")
def sokrat():
    return send_file("compliance-demo.html")


@app.route("/api/health")
def api_health():
    """Lightweight health check for Docker/load balancers."""
    try:
        tree = load_tree()
        return jsonify({"status": "ok", "leaves": sum(
            len(b["leaves"]) for b in tree["branches"].values()
        )})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/boot")
def api_boot():
    """Verify Merkle integrity of the knowledge tree on boot."""
    try:
        tree = load_tree()

        # Primary check: recompute every hash from leaf content up
        tree_ok, integrity_errors = verify_tree_integrity(tree)

        # Secondary check: file checksums
        file_checks = []
        files_ok = True
        for fname in DEMO_TRACKED_FILES:
            fpath = os.path.join(DEMO_DIR, fname)
            if os.path.exists(fpath):
                with open(fpath, "rb") as f:
                    h = hashlib.sha256(f.read()).hexdigest()
                file_checks.append({"file": fname, "hash": h[:24], "status": "OK"})
            else:
                file_checks.append({"file": fname, "hash": None, "status": "MISSING"})
                files_ok = False

        status = "CLEAN" if tree_ok else "MODIFIED"

        # Epistemic health: assess every leaf's belief stance
        epistemic = None
        if _belief_available:
            try:
                from core.knowledge_synapses import load_synapses
                syn_path = os.path.join(DEMO_DIR, "demo_synapses.json")
                synapses = load_synapses(syn_path) if os.path.exists(syn_path) else load_synapses()

                counts = {"confident": 0, "uncertain": 0, "contested": 0, "superseded": 0}
                all_assessments = []
                for branch in tree["branches"].values():
                    for leaf in branch["leaves"]:
                        a = _assess_belief(leaf["id"], tree=tree, synapses=synapses)
                        stance_lower = a["stance"].lower()
                        if stance_lower in counts:
                            counts[stance_lower] += 1
                        all_assessments.append(a)

                total_leaves = sum(counts.values())

                # Surface the 3 most interesting leaves
                # Priority: CONTESTED/SUPERSEDED first, then UNCERTAIN, then lowest-confidence CONFIDENT
                priority_order = {"CONTESTED": 0, "SUPERSEDED": 0, "UNCERTAIN": 1, "CONFIDENT": 2, "NOT_FOUND": 3}
                all_assessments.sort(key=lambda a: (priority_order.get(a["stance"], 9), a["net_confidence"]))
                surfaced = []
                for a in all_assessments[:3]:
                    surfaced.append({
                        "leaf_id": a["leaf_id"],
                        "branch": a["branch"],
                        "content": a["content"],
                        "stance": a["stance"],
                        "net_confidence": round(a["net_confidence"], 2),
                    })

                # Last gardener run from adversarial_validation_run.json
                last_gardener = None
                val_file = os.path.join(DEMO_DIR, "adversarial_validation_run.json")
                if os.path.exists(val_file):
                    try:
                        with open(val_file, "r") as vf:
                            val_data = json.load(vf)
                        last_gardener = val_data.get("run_date") or val_data.get("timestamp")
                    except (json.JSONDecodeError, KeyError):
                        pass

                epistemic = {
                    "total_leaves": total_leaves,
                    **counts,
                    "surfaced": surfaced,
                    "last_gardener_run": last_gardener,
                }
            except Exception as ep_err:
                logger.warning("Epistemic health computation failed: %s", ep_err)

        resp = {
            "status": status,
            "merkle_root": tree.get("root_hash", ""),
            "tree_integrity": "VERIFIED" if tree_ok else "MISMATCH",
            "timestamp": datetime.now(TZ_UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "changed": 0 if tree_ok else 1,
            "missing": 0 if files_ok else sum(1 for f in file_checks if f["status"] == "MISSING"),
            "file_checks": file_checks,
        }
        if integrity_errors:
            resp["integrity_errors"] = integrity_errors
        if epistemic:
            resp["epistemic_health"] = epistemic
        return jsonify(resp)
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
    """Semantic search across the knowledge tree using Ollama embeddings.

    Requires one-time setup: ollama pull nomic-embed-text
    Falls back to keyword search if Ollama is unavailable.
    """
    data = request.get_json()
    query = data.get("query", "").lower().strip()
    if not query:
        return jsonify({"results": [], "query": ""})

    tree = load_tree()

    # Build a lookup from leaf id -> hash (not stored in the search index).
    hash_lookup = {}
    for branch in tree["branches"].values():
        for leaf in branch["leaves"]:
            hash_lookup[leaf["id"]] = leaf.get("hash", "")

    use_keyword_fallback = False
    try:
        raw = knowledge_search.search(query, top_k=3)
        scored = []
        for score, leaf_id, leaf_data in raw:
            scored.append({
                "branch": leaf_data["branch"],
                "content": leaf_data["content"],
                "confidence": leaf_data.get("confidence", 0.7),
                "hash": hash_lookup.get(leaf_id, ""),
                "source": leaf_data.get("source", ""),
                "created": leaf_data.get("created", ""),
                "id": leaf_id,
                "score": round(score, 3),
            })
        if not scored:
            use_keyword_fallback = True
    except Exception as e:
        logger.warning("Semantic search failed (%s), falling back to keyword search.", e)
        use_keyword_fallback = True
        scored = []

    if use_keyword_fallback:
        # Ollama not running, model not pulled, or index empty — keyword search.
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
        scored = scored[:3]

    return jsonify({"results": scored, "query": query, "total_matches": len(scored)})


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


@app.route("/api/gigachat-validation")  # kept for backward compat
@app.route("/api/adversarial-validation")
def api_gigachat_validation():
    """Return adversarial validation run results."""
    validation_file = os.path.join(DEMO_DIR, "adversarial_validation_run.json")
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


@app.route("/api/belief", methods=["POST"])
def api_belief():
    """Assess belief stance for a natural-language query via synapse graph traversal."""
    if not _belief_available:
        return jsonify({"error": "Belief traversal unavailable", "detail": "Could not import core.belief_traversal"})

    data = request.get_json()
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "Empty query"})

    try:
        tree = load_tree()
        # Load synapses from demo dir if available, else fall back to default
        from core.knowledge_synapses import load_synapses
        syn_path = os.path.join(DEMO_DIR, "demo_synapses.json")
        synapses = load_synapses(syn_path) if os.path.exists(syn_path) else load_synapses()

        assessments = _query_belief(query, top_k=3, tree=tree, synapses=synapses)

        # Enrich each assessment with supporting/contradicting leaf details
        for a in assessments:
            leaf_id = a["leaf_id"]
            supporting = []
            contradicting = []
            for s in synapses.get("synapses", []):
                if s["from_leaf"] == leaf_id or s["to_leaf"] == leaf_id:
                    neighbor_id = s["to_leaf"] if s["from_leaf"] == leaf_id else s["from_leaf"]
                    # Find neighbor leaf content
                    for branch in tree["branches"].values():
                        for leaf in branch["leaves"]:
                            if leaf["id"] == neighbor_id:
                                entry = {
                                    "id": neighbor_id,
                                    "content": leaf["content"][:200],
                                    "confidence": leaf["confidence"],
                                    "relation": s["relation"],
                                }
                                if s["relation"] in ("SUPPORTS", "REFINES", "DERIVES_FROM"):
                                    supporting.append(entry)
                                elif s["relation"] == "CONTRADICTS":
                                    contradicting.append(entry)
                                break
            a["supporting"] = supporting
            a["contradicting"] = contradicting

        return jsonify({"assessments": assessments, "query": query})
    except Exception as e:
        return jsonify({"error": "Belief traversal unavailable", "detail": str(e)})


@app.route("/api/belief/recompute", methods=["POST"])
def api_belief_recompute():
    """Recompute all Bayesian confidence updates from scratch."""
    try:
        from core.belief_updater import recompute_all
        from core.knowledge_synapses import load_synapses

        tree = load_tree()
        syn_path = os.path.join(DEMO_DIR, "demo_synapses.json")
        synapses = load_synapses(syn_path) if os.path.exists(syn_path) else load_synapses()

        log_file = os.path.join(DEMO_DIR, "demo_belief_updates.json")
        result = recompute_all(tree, synapses=synapses, log_file=log_file)

        # Save updated tree
        tree["last_updated"] = datetime.now(TZ_UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        from core.knowledge_tree import compute_branch_hash, compute_root_hash
        for branch_name in tree.get("branches", {}):
            tree["branches"][branch_name]["hash"] = compute_branch_hash(
                tree["branches"][branch_name]["leaves"]
            )
        tree["root_hash"] = compute_root_hash(tree)
        with open(DEMO_TREE_FILE, "w", encoding="utf-8") as f:
            json.dump(tree, f, ensure_ascii=False, indent=2)

        return jsonify(result)
    except Exception as e:
        logger.exception("Belief recompute failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/belief/update-log")
def api_belief_update_log():
    """Return the Bayesian confidence update log."""
    try:
        from core.belief_updater import get_update_log
        log_file = os.path.join(DEMO_DIR, "demo_belief_updates.json")
        log = get_update_log(log_file)
        return jsonify({"updates": log})
    except Exception as e:
        return jsonify({"updates": [], "error": str(e)})


@app.route("/api/history")
def api_history():
    """Return the most recent belief changes across all leaves."""
    try:
        from core.belief_history import get_recent_changes
        history_file = os.path.join(DEMO_DIR, "demo_belief_history.json")
        n = request.args.get("n", 20, type=int)
        changes = get_recent_changes(n=n, history_file=history_file)

        # Enrich with leaf content snippets
        tree = load_tree()
        for c in changes:
            for branch in tree["branches"].values():
                for leaf in branch["leaves"]:
                    if leaf["id"] == c["leaf_id"]:
                        c["content_snippet"] = leaf["content"][:80]
                        break

        return jsonify({"changes": changes})
    except Exception as e:
        return jsonify({"changes": [], "error": str(e)})


@app.route("/api/history/<leaf_id>")
def api_history_leaf(leaf_id):
    """Return full version history for one leaf."""
    try:
        from core.belief_history import get_leaf_history
        history_file = os.path.join(DEMO_DIR, "demo_belief_history.json")
        records = get_leaf_history(leaf_id, history_file=history_file)

        # Enrich with leaf content snippet
        tree = load_tree()
        content_snippet = ""
        for branch in tree["branches"].values():
            for leaf in branch["leaves"]:
                if leaf["id"] == leaf_id:
                    content_snippet = leaf["content"][:120]
                    break

        return jsonify({
            "leaf_id": leaf_id,
            "content_snippet": content_snippet,
            "records": records,
        })
    except Exception as e:
        return jsonify({"leaf_id": leaf_id, "records": [], "error": str(e)})


@app.route("/api/history/<leaf_id>/diff")
def api_history_diff(leaf_id):
    """Return diff between two version records of a leaf."""
    try:
        from core.belief_history import diff_versions
        history_file = os.path.join(DEMO_DIR, "demo_belief_history.json")
        v1 = request.args.get("v1", 0, type=int)
        v2 = request.args.get("v2", 1, type=int)
        result = diff_versions(leaf_id, v1, v2, history_file=history_file)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/ingest", methods=["POST"])
def api_ingest():
    """Ingest document content: extract factual claims and commit as leaves."""
    data = request.get_json()
    content = (data.get("content") or "").strip()
    source = data.get("source", "manual").strip() or "manual"

    if not content:
        return jsonify({"error": "Empty content"}), 400
    if len(content) > 50_000:
        return jsonify({"error": "Content too long (max 50,000 chars)"}), 400

    try:
        from core.doc_ingest import extract_claims_from_text, INGEST_BRANCH, DEFAULT_CONFIDENCE

        claims = extract_claims_from_text(content)

        tree = load_tree()

        leaves = []
        for claim in claims:
            leaf_id = add_knowledge(
                tree, INGEST_BRANCH, claim,
                source=source, confidence=DEFAULT_CONFIDENCE,
            )
            leaves.append({
                "id": leaf_id,
                "content": claim,
                "confidence": DEFAULT_CONFIDENCE,
            })

        root_hash = compute_root_hash(tree)

        # Save the updated demo tree
        import json as _json
        tree["last_updated"] = datetime.now(TZ_UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        for branch_name in tree.get("branches", {}):
            from core.knowledge_tree import compute_branch_hash
            tree["branches"][branch_name]["hash"] = compute_branch_hash(
                tree["branches"][branch_name]["leaves"]
            )
        tree["root_hash"] = root_hash
        with open(DEMO_TREE_FILE, "w", encoding="utf-8") as f:
            _json.dump(tree, f, ensure_ascii=False, indent=2)

        return jsonify({
            "leaves": leaves,
            "count": len(leaves),
            "root_hash": root_hash,
            "source": source,
        })

    except Exception as e:
        logger.exception("Ingestion failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/search", methods=["POST"])
def api_search():
    """Dedicated semantic search endpoint.

    POST {"query": "...", "top": 5, "branch": null}
    Returns results with id, content, branch, confidence, score, source.
    Falls back to substring match if Ollama is unavailable.
    """
    data = request.get_json()
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "Empty query"}), 400

    top_k = data.get("top", 5)
    branch_filter = data.get("branch") or None

    tree = load_tree()
    fallback = False
    model = knowledge_search.EMBED_MODEL

    try:
        raw = knowledge_search.search(query, top_k=top_k, branch_filter=branch_filter)
        results = []
        for score, leaf_id, leaf_data in raw:
            results.append({
                "id": leaf_id,
                "content": leaf_data["content"],
                "branch": leaf_data["branch"],
                "confidence": leaf_data.get("confidence", 0.7),
                "score": round(score, 4),
                "source": leaf_data.get("source", ""),
            })
        if not results:
            raise ValueError("no semantic results")
    except Exception as e:
        logger.warning("Semantic search failed (%s), falling back to substring match.", e)
        fallback = True
        keywords = query.lower().split()
        scored = []
        for branch_name, branch in tree["branches"].items():
            if branch_filter and branch_name != branch_filter:
                continue
            for leaf in branch["leaves"]:
                content_lower = leaf["content"].lower()
                hits = sum(1 for kw in keywords if kw in content_lower)
                if hits > 0:
                    score = round(hits * leaf["confidence"], 4)
                    scored.append({
                        "id": leaf["id"],
                        "content": leaf["content"],
                        "branch": branch_name,
                        "confidence": leaf["confidence"],
                        "score": score,
                        "source": leaf["source"],
                    })
        scored.sort(key=lambda x: x["score"], reverse=True)
        results = scored[:top_k]

    resp = {
        "results": results,
        "query": query,
        "model": model,
    }
    if fallback:
        resp["fallback"] = True
    return jsonify(resp)


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
        "demo_mode": DEMO_MODE,
    })


def _maybe_reindex():
    """Trigger background reindex if search index is missing or stale (>1 hour)."""
    index_path = knowledge_search.INDEX_FILE
    stale = True
    if os.path.exists(index_path):
        age = datetime.now(TZ_UTC).timestamp() - os.path.getmtime(index_path)
        stale = age > 3600  # older than 1 hour

    if not stale:
        return

    logger.info("Search index missing or stale — triggering background reindex.")

    def _run():
        try:
            script = os.path.join(os.path.dirname(DEMO_DIR), "core", "knowledge_search.py")
            env = os.environ.copy()
            env["PCIS_BASE_DIR"] = DEMO_DIR
            subprocess.run(
                [sys.executable, script, "--reindex"],
                env=env, timeout=120,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            logger.warning("Background reindex failed: %s", exc)

    threading.Thread(target=_run, daemon=True).start()


if __name__ == "__main__":
    _maybe_reindex()
    host = "0.0.0.0" if os.environ.get("PCIS_DOCKER") else "127.0.0.1"
    print(f"\n  PCIS Demo Server")
    print(f"  Tree: {DEMO_TREE_FILE}")
    print(f"  http://localhost:5555\n")
    app.run(host=host, port=5555, debug=False)
