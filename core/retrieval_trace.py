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
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from knowledge_tree import compute_root_hash, load_tree
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

# Reader-facing phrasing and severity, kept HERE beside the classification they
# describe rather than in a client-side table. A caption emitted from the thing
# it describes has zero distance from the computation and cannot assert a state
# the check did not return.
#
# The phrasing is temporal on purpose — this axis answers "has anything changed
# since this retrieval", never "is the content genuine", which is
# knowledge_tree.verify_tree_integrity's question.
#
# Severity is deliberately coarser than status: three values, so the stylesheet
# needs three classes and the specificity lives in the label. Fewer colours is
# less to keep in step.
DISPLAY_PHRASING = {
    "pass": (
        "unchanged since trace", "ok",
        "This leaf's content still matches what was recorded at retrieval time, "
        "and this check could have failed — so the match means something.",
    ),
    "mismatch": (
        "changed since trace", "changed",
        "This leaf's content differs from what was recorded at retrieval time.",
    ),
    "missing": (
        "removed since trace", "changed",
        "This leaf is no longer in the tree.",
    ),
    "retracted": (
        "withdrawn since trace", "changed",
        "This leaf was retracted or superseded after the trace.",
    ),
}

# What a leaf reads when the comparison could not have failed. Not a status —
# the absence of one.
NO_VERDICT_PHRASING = (
    "no elapsed check", "unknown",
    "This trace was drawn from the tree and the tree has not changed since. "
    "Re-verifying would compare the tree to itself, which cannot fail — so "
    "nothing is claimed. This is the honest state for a fresh retrieval, not a "
    "failure.",
)


def leaf_presentation(wire_status):
    """(label, severity, explanation) for a re-verification status, or for the
    absence of one when ``wire_status`` is None."""
    if wire_status is None:
        return NO_VERDICT_PHRASING
    return DISPLAY_PHRASING[wire_status]


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
    extras: Optional[dict] = None,
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
        extras=dict(extras or {}),
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


TRACE_ENV_VAR = "PCIS_TRACE_RETRIEVAL"


def tracing_enabled() -> bool:
    """Tracing is ON by default; ``PCIS_TRACE_RETRIEVAL=0`` turns it off.

    Consequence worth knowing: with this on, a read command such as
    ``pcis search`` appends to ``data/provenance-ledger.jsonl`` as a side
    effect. That directory is where PCIS already writes everything and is
    gitignored, but writing during a read is new behaviour.
    """
    return os.environ.get(TRACE_ENV_VAR, "1").strip().lower() not in (
        "0", "false", "no", "off", "",
    )


def emit_retrieval_trace(
    *,
    sink: str,
    answer_text: str,
    search_results: Optional[Iterable] = None,
    injection: Optional[list] = None,
    tree: Optional[dict] = None,
    producer_model: Optional[str] = None,
    run_id: Optional[str] = None,
    rendered_truncated_to: Optional[int] = None,
    retractions_applied: Optional[list] = None,
    synapses: Optional[dict] = None,
    ledger_path: Optional[str] = None,
    dedupe: bool = False,
    extras: Optional[dict] = None,
) -> Optional[ProvenanceRecord]:
    """Trace one retrieval and persist it. Never raises.

    Pass ``search_results`` (raw ``knowledge_search.search`` output) for a
    retrieval-only emitter, or ``injection`` — ``[(leaf_id, content)]`` in
    rank order — when the caller already holds the text it fed to a model.

    Returns ``None`` when tracing is disabled, nothing was retrieved, or a
    failure was swallowed. Otherwise returns the record — note that with
    ``dedupe=True`` an already-present ``record_id`` returns the built
    record without appending a second line, so a non-None return means "a
    record exists", not "a line was just written".

    FAILURE POLICY — swallow, warn, never raise. Provenance logging is
    observability, not the product; it must not be able to break a memory
    lookup or a CLI search. The honest cost is that a missing record leaves
    no gap to notice, so coverage is NOT verifiable from the ledger. Nothing
    in PCIS claims coverage — only that traced retrievals are traced.

    ``rendered_truncated_to`` records that the emitter clipped the text for
    display while the hash covers the full retrieved content, so the gap
    between what was retrieved and what was shown is machine-readable
    instead of doc-only. (Recorded in the block's ``extras``; whether it
    deserves a real schema field is a v0.3 question for the contract.)

    ``extras`` passes caller-supplied facts into the same block. It exists so
    a caller does not have to drop to ``log_retrieval`` — and lose the
    never-raises policy above — just to record one more field. Current use:
    ``retrieval_mode`` ("semantic" | "keyword"), which says HOW the leaves
    were selected. Nothing in the v0.2 schema carries that, so a
    keyword-fallback trace is otherwise indistinguishable from a semantic
    one; it is a candidate real field for v0.3 and a contract question for
    the sibling spec.
    """
    if not tracing_enabled():
        return None

    used_search_results = injection is None
    try:
        if injection is None:
            if not search_results:
                return None  # nothing retrieved — nothing to attest
            injection = injection_from_search(search_results)
        if not injection:
            return None

        # Caller extras first, then the named parameter — an explicit
        # argument outranks a same-named key smuggled through the dict.
        extras = dict(extras or {})
        if rendered_truncated_to is not None:
            extras["rendered_truncated_to"] = rendered_truncated_to
        # The emitter knows its own source when it was handed search results:
        # knowledge_search.search reads data/search-index.json and NEVER the
        # tree, so re-verifying against the tree compares two artifacts. A
        # caller passing ``injection`` supplies text from somewhere we cannot
        # see, so it must declare the source itself or the trace is treated as
        # unattestable. See verify_retrieval. [PCIS-ATTEST]
        if used_search_results and "injection_source" not in extras:
            extras["injection_source"] = "index"
        return log_retrieval(
            ledger_path=ledger_path,
            dedupe=dedupe,
            sink=sink,
            answer_text=answer_text,
            injection=injection,
            tree=tree if tree is not None else load_tree(),
            run_id=run_id or f"{sink.rsplit('/', 1)[-1]}-{uuid.uuid4().hex[:12]}",
            # UTC, +00:00 form, microseconds ALWAYS present. timespec is
            # explicit because a bare .isoformat() omits the fractional part
            # when microsecond happens to be 0, and truncation to seconds
            # collapses distinct events into sort ties.
            timestamp=datetime.now(timezone.utc).isoformat(
                timespec="microseconds"
            ),
            producer_model=producer_model,
            retractions_applied=retractions_applied,
            synapses=synapses,
            extras=extras,
        )
    except Exception as e:  # noqa: BLE001 — deliberate: never break retrieval
        print(
            f"  [provenance] retrieval trace not recorded for {sink}: "
            f"{type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return None


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
      injection_source — 'index' | 'tree' | None, from the record's extras
      attestable       — whether a PASS here can be believed (see below)
      attestation_gap  — when not attestable, why, in a reader-facing sentence
      leaves           — how many cited leaves were checked
      ok               — every leaf passes AND the root is unchanged

    THE RULE: a detected difference is always evidence; only a pass needs
    attestability.

    A mismatch proves the comparison is live — it just failed, so it could
    fail. A pass proves nothing unless the check had the capacity to fail. It
    lacks that capacity when the text was injected FROM the tree and verified
    AGAINST that same tree with nothing changed between: comparing a value to
    itself. Everything below — ``injection_source``, the root check — is only
    how that capacity gets computed. The rule is the invariant; the plumbing
    is an implementation detail.

    Consequence: ``attestable`` is False only when every leaf passes and
    nothing independent backs it. Any non-pass status makes the whole result
    reportable, including its passes.

    What even an attestable trace does NOT establish: authenticity. It says
    the tree has not changed since the retrieval, never that the content is
    genuine. Content-versus-its-own-hashes is a separate layer —
    ``knowledge_tree.verify_tree_integrity``.

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
    # ⚠️ root_state is NOT a proxy for "the tree changed". compute_root_hash
    # derives from the STORED branch hashes, so editing a leaf's content
    # without rehashing leaves the root byte-identical while the content
    # differs — which is exactly the naive tamper this module exists to
    # survive. `stale` means "changed AND rehashed". Do not reach for this as
    # a change signal; use the per-leaf statuses, which read content.
    root_state = (
        "current" if root_current == block.tree_root_at_trace else "stale"
    )

    # ATTESTABILITY — does re-verification have independent purchase? A trace
    # whose injected text came FROM the tree, re-verified AGAINST that same
    # tree with nothing changed in between, compares a value to itself: it
    # cannot fail, so a pass proves nothing and must not be presented as one.
    # The distinction is same-ARTIFACT, not same-request.
    #
    #   index-sourced        -> always attestable (index and tree can disagree)
    #   tree-sourced, moved  -> attestable (recorded text vs a changed tree)
    #   tree-sourced, unmoved-> NOT attestable (self-referential)
    #   source unrecorded    -> NOT attestable (fail toward friction)
    #
    # Note what even an attestable trace does NOT establish: authenticity. It
    # says the tree has not changed since the retrieval, never that the content
    # is genuine. Content-vs-its-own-hashes is a separate layer entirely —
    # knowledge_tree.verify_tree_integrity. [PCIS-ATTEST]
    # THE RULE (see docstring): a detected difference is always evidence;
    # only a pass needs attestability. Everything below computes whether the
    # check had the capacity to fail.
    observed_change = any(s != "pass" for s in statuses.values())

    injection_source = (block.extras or {}).get("injection_source")
    if observed_change or root_state == "stale":
        attestable, gap = True, None
    elif injection_source == "index":
        attestable, gap = True, None
    elif injection_source == "tree":
        attestable = False
        gap = ("this trace was drawn from the tree and the tree has not "
               "changed since, so re-verification compares the tree to "
               "itself and cannot fail")
    else:
        attestable = False
        gap = ("the injection source was not recorded and the tree has not "
               "changed since, so it cannot be shown that re-verification is "
               "independent of where the text came from")

    return {
        "re_verification": statuses,
        "display": {k: DISPLAY_STATUS[v] for k, v in statuses.items()},
        "root_recorded": block.tree_root_at_trace,
        "root_current": root_current,
        "root_state": root_state,
        "synapses_loaded": synapses is not None,
        "injection_source": injection_source,
        "attestable": attestable,
        "attestation_gap": gap,
        "leaves": len(statuses),
        # `ok` remains a same-state comparison and is NOT an attestation. It is
        # deliberately not served to any client; see the demo's detail route.
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

    # A self-referential comparison has no verdict to report. Saying
    # "N/N cited leaves resolve, unchanged since trace" here is the exact
    # sentence a cold reader saw printed over tampered content on
    # 2026-07-25. Absent the key (a hand-built dict), keep the old behaviour
    # rather than silently changing what an existing caller means.
    if not result.get("attestable", True):
        return (
            f"retrieval trace: {n} cited {'leaf' if n == 1 else 'leaves'} recorded — "
            f"no elapsed check ({result.get('attestation_gap', 'source unknown')})"
        )

    statuses = result["re_verification"]
    resolved = sum(1 for s in statuses.values() if s == "pass")
    if resolved == n:
        line = (
            f"retrieval trace: {n}/{n} cited leaves resolve, unchanged "
            f"since trace"
        )
    else:
        # Never say "unchanged" while reporting drift — name what happened.
        breakdown = ", ".join(
            f"{count} {DISPLAY_STATUS[status]}"
            for status, count in sorted(
                (
                    (s, sum(1 for v in statuses.values() if v == s))
                    for s in set(statuses.values())
                    if s != "pass"
                ),
                key=lambda pair: pair[0],
            )
        )
        line = f"retrieval trace: {resolved}/{n} cited leaves resolve — {breakdown}"
    if result["root_state"] == "stale":
        line += " (tree root has moved since the trace)"
    if not result["synapses_loaded"]:
        line += " (supersession not checked: no synapse graph)"
    return line
