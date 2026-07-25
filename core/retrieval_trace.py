#!/usr/bin/env python3
"""
retrieval_trace.py — the verified retrieval trace.

WHAT THIS PROVES, EXACTLY
=========================
At answer time it records which leaf ids the retrieval path reported
injecting, a hash of each leaf's content AS INJECTED, and the tree root it
was taken against. Re-verification later re-reads the tree and reports, per
leaf: ``pass``, ``mismatch``, ``missing``, or ``retracted``.

That is **retrieval provenance, not answer provenance**: it establishes
that certain leaves were fed in and still match the record, NOT that the
answer used them. Nothing here compares answer text to leaf content.
Whether a model's output actually drew on a given input lives in model
internals, not in a memory substrate — see ROADMAP.md, "Not ours".

A fully green trace does NOT establish that the answer is correct,
grounded, consistent with the cited leaves, or that the leaves are true. It
does not establish that the cited leaves were the only context. And the
trace is written by the same code path that selected the leaves, so the
producer-cannot-certify-itself invariant does NOT bind it in v0.2.

Do not describe any output of this module as a verified, grounded,
attested, or citation-backed answer.

THE CORE INVARIANT
==================
The recorded hash is a **pure content hash of the text that was actually
injected**, compared against the tree's **current content** for that leaf
id.

The injected text comes from the search index
(core/knowledge_search.py:288 reads data/search-index.json, never the
tree), so a stale index is a real and detectable signal: the model was
shown text that is no longer what the record holds.

Two tempting alternatives are both wrong:

  * Hashing the tree's content at trace time compares a value to itself —
    structurally guaranteed to pass, proving nothing.
  * ``hash_leaf(content, branch, created)`` folds in the branch and
    timestamp. ``incremental_index`` (core/knowledge_search.py:268) stores
    INDEX time as ``created``, so every incrementally-added leaf would
    false-positive; and comparing injected content against the leaf's
    stored ``hash`` field reports pass when content was edited without that
    field being updated.

Tree self-consistency (content vs stored hash vs branch vs root) is a
separate layer: ``knowledge_tree.verify_tree_integrity``. This module does
not duplicate it.

CAVEAT — SUPERSESSION IS BEST-EFFORT
====================================
``retracted`` is honest for soft-prune, which is unconditional. Supersession
is only computed when a synapse graph is actually passed in. PCIS's
``data/synapses.json`` may be absent, in which case a superseded leaf reads
``pass``. That is absence of evidence, not evidence of absence — the
``synapses_loaded`` flag in the result says which case you are in, and it
must be surfaced anywhere a status is displayed.

Spec: provenance-schema-v0.2-2026-07-25.md, held in the upstream
workspace. Set PCIS_SIBLING_WORKSPACE to point the parity tests at it.

No external dependencies. Python 3.10+.
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable, Optional

from knowledge_tree import compute_root_hash
from knowledge_synapses import find_leaf_in_tree
from provenance import (
    ProvenanceRecord,
    RetrievalProvenance,
    VerifierResult,
    classify_leaf_re_verification,
    retrieval_idempotency_key,
    sha256_hex,
)

# The sink label for this trace. Deliberately NOT "verified-answer" — nothing
# about the answer is verified.
DEFAULT_SINK = "pcis.retrieval-trace"

# Reader-facing vocabulary for the per-leaf wire values. The wire values are
# the shared contract; these are display only, mapped 1:1.
DISPLAY_STATUS = {
    "pass": "resolves",
    "mismatch": "drifted",
    "missing": "gone",
    "retracted": "withdrawn",
}


def content_hash(content: str) -> str:
    """Pure SHA-256 of leaf content — no branch, no timestamp.

    Deliberately not ``knowledge_tree.hash_leaf``: see the module docstring.
    This is the value compared on both sides of re-verification, so it must
    depend on nothing but the text itself.
    """
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def injection_from_search(search_results: Iterable) -> list:
    """Turn ``knowledge_search.search`` output into an injection list.

    ``search`` yields ``(score, leaf_id, leaf_data)`` and its ``leaf_data``
    is the INDEX's copy of the content — which is exactly the text that gets
    injected, and exactly what must be hashed. Rank order is preserved.
    """
    return [(leaf_id, leaf_data["content"]) for _score, leaf_id, leaf_data in search_results]


def _is_superseded(synapses: Optional[dict], leaf_id: str) -> bool:
    """True iff some SUPERSEDES synapse points AT this leaf.

    Direction matters: the superseding leaf is ``from_leaf``.
    """
    if not synapses:
        return False
    return any(
        s.get("relation") == "SUPERSEDES" and s.get("to_leaf") == leaf_id
        for s in synapses.get("synapses", [])
    )


def _classify_all(
    recorded_hashes: dict,
    leaf_ids: Iterable,
    tree: dict,
    synapses: Optional[dict],
) -> dict:
    """Classify every recorded leaf id against the tree as it is right now."""
    synapses_loaded = synapses is not None
    out = {}
    for leaf_id in leaf_ids:
        _branch, leaf = find_leaf_in_tree(tree, leaf_id)
        current = content_hash(leaf["content"]) if leaf is not None else None
        out[leaf_id] = classify_leaf_re_verification(
            leaf_id=leaf_id,
            recorded_hash=recorded_hashes[leaf_id],
            current_hash=current,
            is_pruned=bool(leaf.get("pruned")) if leaf is not None else False,
            is_superseded=_is_superseded(synapses, leaf_id),
            synapses_loaded=synapses_loaded,
        )
    return out


def build_retrieval_record(
    *,
    sink: str = DEFAULT_SINK,
    answer_text: str,
    injection: list,
    tree: dict,
    run_id: str,
    timestamp: str,
    actor: str = "cc",
    producer_model: Optional[str] = None,
    retractions_applied: Optional[list] = None,
    synapses: Optional[dict] = None,
    claim_content: Optional[str] = None,
) -> ProvenanceRecord:
    """Write a retrieval trace for one emitted answer.

    Args:
      injection: ordered ``[(leaf_id, content_as_injected)]``, in RANK order.
        Rank is preserved in ``injected_leaf_ids`` because it is observable
        and determines what the model saw first — and it is NOT recoverable
        from ``answer_text_hash``, since two leaves with identical content
        produce a byte-identical answer under either ordering.
      tree: the tree as read at trace time. Re-verification runs immediately
        against it, so an index that has drifted from the tree is caught
        here rather than being recorded as a clean trace.
      retractions_applied: leaves that were filtered OUT of the answer.
        Disjoint from the injected ids (R1).

    ``record_id`` sorts the leaf ids, so a benign reindex that merely
    permuted equal-scoring leaves does not mint a new record for a
    byte-identical answer. Two retrievals differing ONLY in rank therefore
    share a ``record_id``: it is an idempotency key, not a unique event id.
    """
    injected_ids = [leaf_id for leaf_id, _content in injection]
    recorded_hashes = {
        leaf_id: content_hash(content) for leaf_id, content in injection
    }

    re_verification = _classify_all(
        recorded_hashes, injected_ids, tree, synapses
    )
    root = compute_root_hash(tree)

    block = RetrievalProvenance(
        sink=sink,
        answer_text=answer_text,
        answer_text_hash=sha256_hex(answer_text),
        injected_leaf_ids=injected_ids,
        leaf_content_hashes=recorded_hashes,
        re_verification=re_verification,
        tree_root_at_trace=root,
        retractions_applied=list(retractions_applied or []),
        producer_model=producer_model,
    )

    claim = claim_content if claim_content is not None else answer_text
    return ProvenanceRecord(
        record_id=retrieval_idempotency_key(answer_text, injected_ids, root),
        record_kind="retrieval",
        timestamp=timestamp,
        run_id=run_id,
        actor=actor,
        claim_content=claim,
        claim_content_hash=sha256_hex(claim),
        retraction_expectation="normal",
        # Overridden by the record (R3) — the per-leaf map is the truth.
        verifier_result=VerifierResult(status="skipped", method="derived"),
        retrieval=block,
    )


def log_retrieval(
    *,
    ledger_path: Optional[str] = None,
    dedupe: bool = False,
    **kwargs: Any,
) -> ProvenanceRecord:
    """Build a retrieval trace and append it to the provenance ledger.

    Thin composition of :func:`build_retrieval_record` and
    ``provenance_ledger.append_record`` — every other argument is passed
    straight through. Returns the record that was built, whether or not
    ``dedupe`` caused the write to be skipped.

    The ledger is append-only and NOT hash-chained (v0.3), so a persisted
    trace is a record of what the retriever reported, not tamper-evident
    proof that the line has not been altered since.
    """
    from provenance_ledger import append_record

    record = build_retrieval_record(**kwargs)
    append_record(record, ledger_path, dedupe=dedupe)
    return record


def verify_retrieval(
    record: ProvenanceRecord,
    *,
    tree: dict,
    synapses: Optional[dict] = None,
) -> dict:
    """Re-verify a recorded trace against a tree read now.

    Returns a dict with:
      re_verification  — leaf_id → pass | mismatch | missing | retracted
      display          — leaf_id → resolves | drifted | gone | withdrawn
      root_recorded    — the root the trace was anchored to
      root_current     — the root now
      root_state       — 'current' | 'stale'
      synapses_loaded  — False means supersession was NOT checked; a
                         superseded leaf reads 'pass'. Surface this.
      leaves           — how many cited leaves were checked
      ok               — every leaf passes AND the root is unchanged

    ``ok`` is not a statement about the answer. It means: the cited leaves
    still say what the record says they said, against the tree state the
    trace was anchored to.
    """
    if record.retrieval is None:
        raise ValueError(
            "verify_retrieval requires a retrieval record; got "
            f"record_kind={record.record_kind!r}"
        )

    block = record.retrieval
    statuses = _classify_all(
        block.leaf_content_hashes,
        block.injected_leaf_ids,
        tree,
        synapses,
    )
    root_current = compute_root_hash(tree)
    root_state = (
        "current" if root_current == block.tree_root_at_trace else "stale"
    )

    return {
        "re_verification": statuses,
        "display": {k: DISPLAY_STATUS[v] for k, v in statuses.items()},
        "root_recorded": block.tree_root_at_trace,
        "root_current": root_current,
        "root_state": root_state,
        "synapses_loaded": synapses is not None,
        "leaves": len(statuses),
        "ok": root_state == "current"
        and all(s == "pass" for s in statuses.values()),
    }


def summarize(result: dict) -> str:
    """One reader-facing line. Never a bare 'Verified' chip.

    An empty trace must not render as all-pass — it reads as "no cited
    leaves", because a green badge over zero leaves looks identical to a
    green badge over twelve.
    """
    n = result["leaves"]
    if not n:
        return "retrieval trace: no cited leaves"
    resolved = sum(1 for s in result["re_verification"].values() if s == "pass")
    line = (
        f"retrieval trace: {resolved}/{n} cited leaves resolve, "
        f"unchanged since trace"
    )
    if result["root_state"] == "stale":
        line += " (tree root has moved since the trace)"
    if not result["synapses_loaded"]:
        line += " (supersession not checked: no synapse graph)"
    return line
