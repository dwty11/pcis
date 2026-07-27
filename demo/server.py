#!/usr/bin/env python3
# ⚠️  DO NOT run this file directly for demos.
# Use: bash start_demo.sh (from repo root)
# Direct invocation reads data/tree.json if it exists — start_demo.sh reads demo/demo_tree.json.
"""
PCIS Demo Server
Self-contained demo: uses demo_tree.json for all endpoints.
Boot integrity check hashes the demo's own files — no external workspace required.
"""

import hashlib
import json
import logging
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
import urllib.request
import uuid
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, request, send_file

try:  # keep emoji / box-drawing output alive on a non-UTF-8 console (e.g. RU-Windows cp1251)
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

# Point knowledge_search at the demo tree before importing it.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
# core/ too: core modules import each other by bare name (the repo's
# convention), so core.retrieval_trace cannot import without it.
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core")
)
import core.knowledge_search as knowledge_search
from core.knowledge_tree import verify_tree_integrity, add_knowledge, compute_root_hash
from core.root_report import build_root_report, digest_file, root_claim

try:
    from core.belief_traversal import query_belief as _query_belief, assess_belief as _assess_belief
    _belief_available = True
except ImportError:
    _belief_available = False

logger = logging.getLogger(__name__)

app = Flask(__name__)

DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
# The tree the demo server reads/writes. Defaults to the shipped demo_tree.json;
# PCIS_DEMO_TREE_FILE overrides it so tests (and any caller) can point the server at
# a private copy and never mutate the shipped file. Backward-compatible: unset = default.
DEMO_TREE_FILE = os.environ.get("PCIS_DEMO_TREE_FILE") or os.path.join(DEMO_DIR, "demo_tree.json")

# Override knowledge_search paths to use the demo tree and its own index.
knowledge_search.TREE_FILE = DEMO_TREE_FILE
knowledge_search.INDEX_FILE = os.path.join(DEMO_DIR, "demo_search_index.json")
TZ_UTC = timezone.utc

# demo_mode=True uses demo_tree.json; False uses data/tree.json
def _load_demo_mode():
    config_path = os.path.join(DEMO_DIR, "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
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
    with open(DEMO_TREE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# Cap on the provenance listing. The route also returns the untruncated
# total, so a capped list is visibly capped rather than silently complete.
PROVENANCE_LIST_LIMIT = 50


# Every status api_boot can put in `status`.
BOOT_STATUSES = ("CLEAN", "MODIFIED", "UNVERIFIABLE", "ERROR")

# Every per-file status api_boot can emit. The headline vocabulary above was
# guarded by an exported constant and a test; this one was not, one level down.
FILE_STATUSES = ("OK", "MODIFIED", "MISSING", "UNTRACKED", "NO_MANIFEST")

# Statuses that mean "this file was compared and it matched". Membership here,
# not absence from a failure list, is what earns CLEAN.
_FILE_STATUS_GOOD = frozenset({"OK"})
# Statuses that mean "this file definitely differs from the baseline".
_FILE_STATUS_BAD = frozenset({"MODIFIED", "MISSING"})


def _boot_headline(file_statuses, tree_ok):
    """Return (status, severity) for the boot headline.

    Both come from this one function so they cannot disagree: severity is not a
    lookup table the client keeps, it is what this classification already
    decided. The client styles on severity, so a status added here carries its
    own presentation instead of falling through to unstyled default text.

    INVARIANT(test_unknown_file_status_is_unverifiable): a per-file status that
    is not explicitly known-good must never produce CLEAN. Membership in
    _FILE_STATUS_GOOD is required — absence from a bad-list is not enough.
    INVARIANT(test_zero_verifications_is_not_clean): CLEAN must mean checks were
    made and passed, never that none were made.
    """
    seen = set(file_statuses)
    if not tree_ok or (seen & _FILE_STATUS_BAD):
        return "MODIFIED", "bad"
    if seen and seen <= _FILE_STATUS_GOOD:
        return "CLEAN", "ok"
    return "UNVERIFIABLE", "unknown"


def _file_check(fname, short_hash, status):
    """One file's result, carrying the presentation its own status implies."""
    label, severity = _file_status_display(status)
    return {"file": fname, "hash": short_hash, "status": status,
            "label": label, "severity": severity}


def _file_status_display(status):
    """Label and severity DERIVED from the classification that drives behaviour.

    Not a parallel presentation table: severity reads the same sets
    _boot_headline decides on, so a status moved between them changes colour
    automatically, and a new status renders as unknown rather than as a
    hardcoded tick. The label is the status itself, so no string can assert a
    state the check did not return.
    """
    if status in _FILE_STATUS_GOOD:
        severity = "ok"
    elif status in _FILE_STATUS_BAD:
        severity = "bad"
    else:
        severity = "unknown"
    return status.replace("_", " "), severity


def _load_manifest():
    """The stored file manifest {filename: sha256}, or None if there isn't one.

    None is deliberately distinct from an empty dict: "no manifest" must render
    as NO_MANIFEST, never as a pass. A boot check with nothing to compare
    against is exactly what shipped a green tick over a tampered file.
    """
    path = os.path.join(DEMO_DIR, "demo_manifest.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    files = data.get("files") if isinstance(data, dict) else None
    return files if isinstance(files, dict) else None


def _scope_note(sink):
    """What this record does and does not establish — per emitter.

    Not one shared string: /api/query and /api/search return retrieved leaves
    and generate nothing, while run-validation feeds a leaf to a model and
    shows its output. Copy written for a generation path, pasted onto a
    retrieval-only one, asserts something nobody checked.
    """
    if sink.endswith("run-validation"):
        return (
            "Retrieval provenance. Records which leaf was fed to the model and "
            "whether it has changed since. It does not establish that the "
            "challenge text is correct, or that the model actually used the leaf."
        )
    return (
        "Retrieval provenance. Records which leaves this search returned and "
        "whether they have changed since. It does not check that the leaves are "
        "true, and it is not a claim that these are the only or best matches."
    )


def _integrity_display(ok):
    """(label, severity) for a content-hash check, from its return value.

    Three outcomes because the check has three: matched, did not match, and
    could not be performed. `None` must never render as a pass.
    """
    if ok is True:
        return "content matches this hash", "ok"
    if ok is False:
        return "CONTENT DOES NOT MATCH THIS HASH", "bad"
    return "integrity unchecked", "unknown"


def _leaf_row(leaf_id, verify_result, attestable):
    """One cited leaf, carrying the phrasing its own verdict implies."""
    from core.retrieval_trace import leaf_presentation

    wire = verify_result["re_verification"].get(leaf_id) if attestable else None
    label, severity, explanation = leaf_presentation(wire)
    return {
        "id": leaf_id,
        "status": verify_result["display"][leaf_id] if attestable else None,
        "label": label,
        "severity": severity,
        "explanation": explanation,
    }


def _content_hash_ok(leaf, branch_name):
    """Does this leaf's content still hash to its own stored value?

    TREE INTEGRITY — a different question from the retrieval trace, and the
    only one of the two that catches a tamper made BEFORE a trace was taken.
    Uses the same primitive as knowledge_tree.verify_tree_integrity rather
    than parsing that function's error strings.
    """
    try:
        from core.knowledge_tree import hash_leaf

        return hash_leaf(leaf["content"], branch_name, leaf["created"]) == leaf.get("hash")
    except Exception:
        return None  # unknown — never silently "ok"


def _emit_route_trace(*, sink, rows, retrieval_mode, tree):
    """Trace one browser-facing retrieval. Never raises.

    ``rows`` are the result dicts the route is about to return; each carries
    the leaf id and the exact content the browser will be shown, so hashing
    them records the copy that was actually injected.

    No model produced an answer on these routes, so the emitted "answer" is
    the result set itself and ``producer_model`` stays None to say so — the
    convention set at agent-plugin/plugin.py:163. Reading a value into
    ``producer_model`` here would assert a generation that never happened.

    ``tree`` is passed in rather than re-loaded: these routes serve the demo
    tree, and the emitter's own default would anchor the record on a
    different one.
    """
    if not rows:
        return None  # nothing retrieved — nothing to attest
    from core.retrieval_trace import emit_retrieval_trace

    record = emit_retrieval_trace(
        sink=sink,
        injection=[(r["id"], r["content"]) for r in rows],
        answer_text=json.dumps(rows, sort_keys=True, ensure_ascii=False),
        tree=tree,
        extras={
            "retrieval_mode": retrieval_mode,
            # Both browser paths hand over text they already hold, so the
            # emitter cannot infer the source. Semantic came from the search
            # index; keyword fallback read the tree — and a tree-sourced trace
            # re-verified against that same tree proves nothing. [PCIS-ATTEST]
            "injection_source": "index" if retrieval_mode == "semantic" else "tree",
        },
    )
    # None when tracing is off or the write failed. The route reports that as
    # a null id so the client can say "not recorded" — silence would make a
    # broken emitter indistinguishable from a working one.
    return record.record_id if record is not None else None


def _load_demo_synapses():
    """The demo synapse graph, or None when there is no real one.

    Deliberately NOT core.knowledge_synapses.load_synapses, which this file
    uses elsewhere for belief assessment, because two of its behaviours are
    wrong inside this path:

      * a missing file yields a fully-formed EMPTY graph, and passing that to
        verify_retrieval reports ``synapses_loaded=True`` — claiming
        supersession was checked when no graph exists. A superseded leaf
        reads ``resolves`` in that state, so the false claim is the dangerous
        direction.
      * a corrupt file calls ``sys.exit(1)``, which from inside a request
        takes the server down.

    An existing-but-empty graph also returns None: it is indistinguishable
    from no graph to a reader, and understating the check is the safe error.
    """
    syn_path = os.path.join(DEMO_DIR, "demo_synapses.json")
    if not os.path.exists(syn_path):
        return None
    try:
        with open(syn_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("synapses"):
        return None
    return data


def _clip(text, n):
    """Truncate for display, adding an ellipsis when the original was longer.
    Truncation with no marker reads as the whole value; the ellipsis signals more."""
    text = text or ""
    return text if len(text) <= n else text[:n] + "..."


def _landing_file():
    # hub.html is an optional, gitignored, deployment-specific landing page.
    # Fall back to the shipped demo UI so a fresh clone serves HTML, not a 500.
    # Absolute paths keep this correct regardless of the server's working dir.
    hub = os.path.join(DEMO_DIR, "hub.html")
    return hub if os.path.exists(hub) else os.path.join(DEMO_DIR, "index.html")


@app.route("/")
def index():
    return send_file(_landing_file())


@app.route("/hub")
def hub():
    return send_file(_landing_file())


@app.route("/demo")
def demo():
    return send_file(os.path.join(DEMO_DIR, "index.html"))


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


def _last_gardener_run():
    """Most recent validation run_date, if any (read-only)."""
    for name in ("external_validation_run.json", "adversarial_validation_run.json"):
        p = os.path.join(DEMO_DIR, name)
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                return d.get("run_date") or d.get("timestamp")
            except (json.JSONDecodeError, KeyError):
                pass
    return None


@app.route("/api/boot")
def api_boot():
    """Verify Merkle integrity of the knowledge tree on boot."""
    try:
        tree = load_tree()

        # Primary check: recompute every hash from leaf content up
        tree_ok, integrity_errors = verify_tree_integrity(tree)

        # Secondary check: file checksums, ACTUALLY compared against a stored
        # manifest. This used to append a literal "OK" per file whose only
        # alternative was MISSING — so a tampered file showed a changed hash
        # beside a green tick, on the tab whose caption promised comparison.
        # Regenerate the manifest with: python3 demo/make_manifest.py
        manifest = _load_manifest()
        file_checks = []
        for fname in DEMO_TRACKED_FILES:
            fpath = os.path.join(DEMO_DIR, fname)
            if not os.path.exists(fpath):
                file_checks.append(_file_check(fname, None, "MISSING"))
                continue
            with open(fpath, "rb") as f:
                h = hashlib.sha256(f.read()).hexdigest()
            if manifest is None:
                st = "NO_MANIFEST"      # nothing to compare against
            elif fname not in manifest:
                st = "UNTRACKED"        # manifest exists but says nothing about this file
            elif manifest[fname] == h:
                st = "OK"
            else:
                st = "MODIFIED"
            file_checks.append(_file_check(fname, h[:24], st))

        # The headline is DERIVED from the per-file statuses rather than
        # accumulated into a boolean as they are produced. The boolean version
        # had to remember to flip in every failing branch and did not: MISSING
        # and MODIFIED set it, NO_MANIFEST and UNTRACKED did not, so three
        # "NO MANIFEST" lines sat under a glowing green CLEAN.
        status, status_severity = _boot_headline(
            {f["status"] for f in file_checks}, tree_ok)
        files_ok = status == "CLEAN"

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

                # Last gardener run from the shipped validation run file.
                last_gardener = _last_gardener_run()

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
            # Styling travels WITH the value that decided it, so the client
            # never keeps a copy of this vocabulary to drift from.
            "status_severity": status_severity,
            # PROVENANCE OF THESE TWO VALUES, because the caption used to get
            # this wrong: `stored` is read verbatim from the tree file and is
            # NOT computed at boot; `recomputed` is derived now from the tree's
            # branch hashes. NEITHER is a function of the file hashes above.
            # The terminal line that said "Computing Merkle root from N file
            # hashes" named a mechanism no value here comes from.
            "merkle_root": tree.get("root_hash", ""),
            "merkle_root_stored": tree.get("root_hash", ""),
            "merkle_root_recomputed": compute_root_hash(tree),
            "manifest_present": manifest is not None,
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
                "content": _clip(leaf["content"], 200),
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
                "content": _clip(l["content"], 300),
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
    integrity_lookup = {}
    for branch_name, branch in tree["branches"].items():
        for leaf in branch["leaves"]:
            hash_lookup[leaf["id"]] = leaf.get("hash", "")
            integrity_lookup[leaf["id"]] = _content_hash_ok(leaf, branch_name)

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
                # Integrity is always checked against the TREE, even when the
                # displayed text came from the index: the question is whether
                # the tree's content matches the tree's own stored hash.
                "content_hash_ok": integrity_lookup.get(leaf_id),
                "integrity": _integrity_display(integrity_lookup.get(leaf_id)),
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
                        "content_hash_ok": _content_hash_ok(leaf, branch_name),
                        "integrity": _integrity_display(_content_hash_ok(leaf, branch_name)),
                    })
        scored.sort(key=lambda x: x["score"], reverse=True)
        scored = scored[:3]

    # Emitted once, AFTER the fallback branch, so both retrieval paths are
    # covered by one call. The two paths inject text from different sources —
    # semantic from the search index, keyword from the tree — but both
    # converge on `scored`, whose dicts carry the id and the exact content
    # handed to the browser, so `injection` is correct either way.
    #
    # This is the path a stranger actually clicks, and it needs no Ollama on
    # the keyword branch, so a fresh clone produces records out of the box.
    record_id = _emit_route_trace(
        sink="pcis.retrieval-trace/demo.query",
        rows=scored,
        retrieval_mode="keyword" if use_keyword_fallback else "semantic",
        tree=tree,
    )

    return jsonify({
        "results": scored,
        "query": query,
        "total_matches": len(scored),
        "provenance_record_id": record_id,
    })


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


@app.route("/api/external-validation")
@app.route("/api/adversarial-validation")
def api_external_validation():
    """Return adversarial validation run results."""
    validation_file = os.path.join(DEMO_DIR, "external_validation_run.json")
    if not os.path.exists(validation_file):
        validation_file = os.path.join(DEMO_DIR, "adversarial_validation_run.json")
    if not os.path.exists(validation_file):
        return jsonify({"status": "not_run", "message": "Run adversarial_validator.py first"})
    with open(validation_file, "r", encoding="utf-8") as f:
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
    # CAPTION PROVENANCE: root_claim is DERIVED from the artifact here, once,
    # rather than inferred by each client from a bare before/after pair. The
    # dashboard used to key on `before !== after` alone, so a projected root
    # rendered as "MERKLE ROOT TRANSITION" for a tree whose bytes never changed.
    # A client cannot mis-infer a verdict it is handed.
    data["root_claim"] = root_claim(data)
    return jsonify(data)


@app.route("/api/run-validation", methods=["POST"])
def api_run_validation():
    """Run on-demand adversarial validation using local Ollama (qwen3:14b)."""
    try:
        tree = load_tree()

        # Collect all non-counter leaves
        candidates = []
        for branch_name, branch in tree["branches"].items():
            for leaf in branch["leaves"]:
                if not leaf["content"].startswith("COUNTER:"):
                    candidates.append((branch_name, leaf))

        if len(candidates) < 3:
            return jsonify({"error": "Not enough non-counter leaves to challenge"}), 400

        chosen = random.sample(candidates, 3)

        # Get current root hash
        # DERIVED, to match merkle_root_after. This read the STORED root_hash
        # field while `after` was a fresh compute_root_hash — so a stale stored
        # root made the two differ for that reason alone, and the UI captioned a
        # difference in DERIVATION METHOD as a change over TIME. Both ends of a
        # before/after pair must be measured the same way or the comparison is
        # not about time at all. [PCIS-CAPTION-PROVENANCE]
        # Digest the tree BEFORE the route does anything, so whether it was
        # written is read off the bytes rather than assumed by this function.
        _tree_digest_before = digest_file(DEMO_TREE_FILE)
        merkle_root_before = compute_root_hash(tree)

        # One provenance trace per challenged leaf. This route makes ONE model
        # call per leaf, each prompt carrying exactly one leaf's content, so
        # three one-leaf-one-answer records are the honest shape — a single
        # record over three leaves would blur three separate generations into
        # one much weaker claim. All three share a run_id.
        #
        # NOTE: candidates come from load_tree(), never the search index, so
        # the injected text here is TREE content. The index-vs-tree staleness
        # signal does not apply to this emitter; post-trace drift still does.
        from core.retrieval_trace import emit_retrieval_trace

        validation_run_id = f"demo-run-validation-{uuid.uuid4().hex[:12]}"

        counters = []
        for branch_name, leaf in chosen:
            prompt = (
                "You are an adversarial reviewer. Challenge this belief in "
                "1-2 sentences, focusing on what could be wrong or missing: "
                + leaf["content"]
            )
            payload = json.dumps({"model": "qwen3:14b", "prompt": prompt, "stream": False}).encode()
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode())
            challenge_text = result.get("response", "").strip()

            counters.append({
                "challenged_id": leaf["id"],
                "challenge": challenge_text,
                "confidence": 0.6,
                "model": "qwen3:14b",
                "branch": branch_name,
            })

            if challenge_text:
                # Anchored on the tree passed in, which is the same object
                # merkle_root_before was derived from six lines earlier — both
                # via compute_root_hash, not the stored root_hash field.
                # (This comment previously said merkle_root_before "reads the
                # stored root_hash", which stopped being true when that line
                # was fixed and the comment was not.)
                emit_retrieval_trace(
                    sink="pcis.retrieval-trace/demo.run-validation",
                    injection=[(leaf["id"], leaf["content"])],
                    answer_text=challenge_text,
                    tree=tree,
                    producer_model="qwen3:14b",
                    run_id=validation_run_id,
                )

        # Build the result document
        run_data = {
            "run_date": datetime.now(TZ_UTC).isoformat(timespec="microseconds"),
            "model": "qwen3:14b",
            "provider": "local-qwen",
            "entries_challenged": 3,
            "counters": counters,
        }
        # Same shape as the validator, for the same reason: this route does not
        # write the tree either, so it must not name an after-root. Whether a
        # write happened is read off the file's bytes, not asserted here.
        run_data.update(build_root_report(
            root_before=merkle_root_before,
            root_projected=compute_root_hash(load_tree()),
            tree_path=DEMO_TREE_FILE,
            digest_before=_tree_digest_before,
        ))

        out_path = os.path.join(DEMO_DIR, "external_validation_run.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(run_data, f, ensure_ascii=False, indent=2)

        return jsonify(run_data)

    except urllib.error.URLError as e:
        # Same graceful shape as /api/ingest — friendly + flagged, never the raw
        # "<urlopen error ...>" string (the client renders it as an inline banner).
        logger.warning("Live validation unavailable — local LLM unreachable: %s", e)
        return jsonify({
            "error": "Live validation needs a local LLM (Ollama), which is unreachable. "
                     "Start it (`ollama serve`) and pull the model, then retry.",
            "ollama_unavailable": True,
        }), 503
    except Exception as e:
        logger.exception("Live validation failed")
        return jsonify({"error": "Live validation failed unexpectedly — check the server log."}), 500


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

        # Relevance gate: check semantic similarity before assessing
        RELEVANCE_THRESHOLD = 0.40
        try:
            from core.knowledge_search import search as _search
            search_results = _search(query, top_k=3, min_score=0.0)
            if search_results and search_results[0][0] < RELEVANCE_THRESHOLD:
                return jsonify({"assessments": [{
                    "leaf_id": "",
                    "content": "",
                    "branch": "",
                    "base_confidence": 0.0,
                    "net_confidence": 0.0,
                    "stance": "OUT_OF_SCOPE",
                    "reasoning": (
                        f"Query did not match any belief in the knowledge base "
                        f"(best similarity: {search_results[0][0]:.2f}, threshold: {RELEVANCE_THRESHOLD:.2f}). "
                        f"Insufficient data to assess."
                    ),
                    "support_count": 0,
                    "contradiction_count": 0,
                    "superseded": False,
                    "depth_reached": 0,
                    "supporting": [],
                    "contradicting": [],
                }], "query": query})
        except Exception:
            pass

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
                                    "content": _clip(leaf["content"], 200),
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
        return jsonify({"error": "Belief recompute failed unexpectedly — check the server log."}), 500


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
                        c["content_snippet"] = _clip(leaf["content"], 80)
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
                    content_snippet = _clip(leaf["content"], 120)
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

    except urllib.error.URLError as e:
        # Ingestion needs a local LLM to extract claims — it can't keyword-fallback
        # the way /api/search does. Degrade gracefully with an actionable message
        # instead of dumping a raw "<urlopen error ...>" 500 to the page.
        logger.warning("Ingestion unavailable — local LLM unreachable: %s", e)
        return jsonify({
            "error": "Claim extraction needs a local LLM (Ollama), which is unreachable. "
                     "Start it (`ollama serve`) and pull the model, then retry.",
            "ollama_unavailable": True,
        }), 503
    except Exception as e:
        logger.exception("Ingestion failed")
        return jsonify({"error": "Ingestion failed unexpectedly — check the server log."}), 500


@app.route("/api/ingest/upload", methods=["POST"])
def api_ingest_upload():
    """Accept a PDF or TXT file upload, extract text, and return it."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    uploaded = request.files["file"]
    filename = uploaded.filename or ""
    ext = os.path.splitext(filename)[1].lower()

    if ext not in (".pdf", ".txt"):
        return jsonify({"error": f"Unsupported file type: {ext or '(none)'}"}), 400

    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            uploaded.save(tmp)
            tmp_path = tmp.name

        if ext == ".pdf":
            from core.doc_ingest import _read_pdf
            text = _read_pdf(tmp_path)
        else:
            with open(tmp_path, "r", encoding="utf-8") as f:
                text = f.read()

        return jsonify({
            "text": text,
            "filename": filename,
            "chars": len(text),
        })
    except Exception as e:
        logger.exception("File upload processing failed")
        return jsonify({"error": "File upload processing failed unexpectedly — check the server log."}), 500
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


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
    integrity_lookup = {
        leaf["id"]: _content_hash_ok(leaf, bname)
        for bname, branch in tree["branches"].items()
        for leaf in branch["leaves"]
    }
    hash_lookup = {
        leaf["id"]: leaf.get("hash", "")
        for branch in tree["branches"].values()
        for leaf in branch["leaves"]
    }

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
                "hash": hash_lookup.get(leaf_id, ""),
                "content_hash_ok": integrity_lookup.get(leaf_id),
                "integrity": _integrity_display(integrity_lookup.get(leaf_id)),
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
                        "hash": leaf.get("hash", ""),
                        "content_hash_ok": integrity_lookup.get(leaf["id"]),
                        "integrity": _integrity_display(integrity_lookup.get(leaf["id"])),
                    })
        scored.sort(key=lambda x: x["score"], reverse=True)
        results = scored[:top_k]

    record_id = _emit_route_trace(
        sink="pcis.retrieval-trace/demo.search",
        rows=results,
        retrieval_mode="keyword" if fallback else "semantic",
        tree=tree,
    )

    resp = {
        "results": results,
        "query": query,
        "model": model,
        "provenance_record_id": record_id,
    }
    if fallback:
        resp["fallback"] = True
    return jsonify(resp)


@app.route("/api/provenance")
def api_provenance_list():
    """Recent retrieval traces, newest first.

    This lists what was RECORDED. It does not assert the list is complete:
    emission swallows its own failures by design (provenance must never be
    able to break a search), so a missing record leaves no gap to notice and
    coverage is not verifiable from the ledger. The ledger is append-only and
    deliberately not hash-chained — see core/provenance_ledger.py.
    """
    from core.provenance_ledger import load_ledger

    try:
        records = load_ledger()
    except Exception as e:  # noqa: BLE001 — a bad ledger must not 500 the demo
        logger.warning("Provenance ledger unreadable (%s)", type(e).__name__)
        return jsonify({"records": [], "total": 0, "unreadable": True})

    rows = []
    for rec in records:
        block = rec.retrieval
        if block is None:
            continue  # intake records are a different kind
        rows.append({
            "record_id": rec.record_id,
            "timestamp": rec.timestamp,
            "sink": block.sink,
            "leaves": len(block.injected_leaf_ids),
            "retrieval_mode": block.extras.get("retrieval_mode"),
        })

    rows.sort(key=lambda r: r["timestamp"], reverse=True)
    # `total` is the untruncated count, so a capped list reads as capped
    # rather than as "that is all there is".
    return jsonify({"records": rows[:PROVENANCE_LIST_LIMIT], "total": len(rows)})


@app.route("/api/provenance/<record_id>")
def api_provenance_detail(record_id):
    """Re-verify one recorded trace against the tree as it is right now.

    Serves the honest summary line and per-leaf DISPLAY statuses. It
    deliberately does NOT serve verify_retrieval's ``ok`` field: that is
    documented as "not a statement about the answer", and shipping it to a
    browser invites the bare green "Verified" chip the trace module bans.
    A client cannot render one from this payload without inventing it.
    """
    from core.provenance_ledger import find_by_record_id
    from core.retrieval_trace import summarize, verify_retrieval

    try:
        record = find_by_record_id(record_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("Provenance lookup failed (%s)", type(e).__name__)
        record = None

    if record is None or record.retrieval is None:
        return jsonify({"error": "no such retrieval record"}), 404

    block = record.retrieval
    result = verify_retrieval(
        record, tree=load_tree(), synapses=_load_demo_synapses()
    )
    display = result["display"]

    # When the comparison is self-referential there IS no verdict, so none is
    # sent. Same structural choice as never serving `ok`: a client cannot
    # render a status it was not given. [PCIS-ATTEST]
    attestable = result["attestable"]

    return jsonify({
        "record_id": record.record_id,
        "timestamp": record.timestamp,
        "sink": block.sink,
        "retrieval_mode": block.extras.get("retrieval_mode"),
        "injection_source": result["injection_source"],
        "attestable": attestable,
        "attestation_gap": result["attestation_gap"],
        "scope_note": _scope_note(block.sink),
        "summary": summarize(result),
        # Presentation travels with the verdict, from core.retrieval_trace,
        # so the client keeps no vocabulary of its own to drift from.
        "leaves": [_leaf_row(leaf_id, result, attestable)
                   for leaf_id in block.injected_leaf_ids],
        "root_state": result["root_state"],
        # Always present: a superseded leaf reads "resolves" when no graph was
        # loaded, so the reader has to be told which case they are looking at.
        "synapses_loaded": result["synapses_loaded"],
    })


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
        "last_gardener_run": _last_gardener_run(),
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
    import argparse
    parser = argparse.ArgumentParser(description="PCIS Demo Server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5555)
    args = parser.parse_args()

    _maybe_reindex()
    print(f"\n  PCIS Demo Server")
    print(f"  Tree: {DEMO_TREE_FILE}")
    print(f"  http://{args.host}:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=False)
