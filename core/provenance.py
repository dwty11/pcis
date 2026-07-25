#!/usr/bin/env python3
"""
provenance.py — ProvenanceRecord v0.2, PCIS's implementation of the shared
intake/retrieval provenance contract.

ONE CONTRACT, TWO CODEBASES, NO SHARED CODE
===========================================
The same contract is implemented independently in the upstream substrate
PCIS was extracted from. That is deliberate: importing across the two
codebases would re-couple them, which is exactly what PCIS's sanitization
removed. The two implementations are held in sync by
tests/test_schema_parity.py, which asserts this module against the contract
rather than sharing a line with the other side.

Spec: provenance-schema-v0.2-2026-07-25.md, held in the upstream
workspace. Set PCIS_SIBLING_WORKSPACE to point the parity tests at it.

WHAT A RETRIEVAL RECORD PROVES
==============================
Very little about the answer, and the docstrings here say so on purpose.
A retrieval record fixes, at answer time, WHICH leaf ids the retrieval
path reported injecting, the hash of each leaf's content AS INJECTED, and
the tree root it was taken against. Re-verification later re-reads the
tree and reports, per leaf, whether that text is still there.

It does NOT establish that the model read, used, or was influenced by any
cited leaf, nor that the answer is consistent with them. Nothing here
compares answer text to leaf content. Answer provenance is not closable
from this layer (see ROADMAP.md "Not ours"). Do not describe any of this
as a verified, grounded, or attested answer.

Not enforced for retrieval records in v0.2: the producer-cannot-certify-
itself invariant. ``assert_self_certification_blocked`` exists and works,
but the retrieval path writes its own trace, so nothing external attests
it.

No external dependencies. Python 3.10+.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


SCHEMA_VERSION = "0.2"

# === Enums ==================================================================

RECORD_KINDS = ("intake", "retrieval")
# 'architect' is a role name, not a system name. v0.2 renamed it from a
# private agent's name: a public schema whose actor vocabulary names a
# private system is a leak in the contract itself, and it would be baked
# into every line of an append-only ledger format, permanently.
ACTORS = ("architect", "cc", "roc", "gardener", "user")
SOURCE_TYPES = (
    "handoff",
    "gardener",
    "user",
    "init",
    "roc-cold-read",
    "roc-maintenance",
)
SOURCE_LABELS = ("PROVEN", "UNVERIFIED", "UNTESTED")  # open set; Roc to extend
CONFLICT_POLICIES = ("supersede", "keep-both", "linked")
RETRACTION_EXPECTATIONS = ("normal", "high")
VERIFIER_STATUSES = ("pass", "fail", "skipped")
VERIFIER_METHODS = (
    "content_hash",
    "line_match",
    "full_text",
    "parser_grounded",
    "derived",
    "none",
)
# V2: 'retracted' joins the per-leaf vocabulary.
RE_VERIFICATION_STATUSES = ("pass", "mismatch", "missing", "retracted")

REDACTION_PLACEHOLDER = "[REDACTED]"

# Required on the wire (R4). A line missing any of these is malformed and
# must not construct a record.
REQUIRED_FIELDS = (
    "record_id",
    "record_kind",
    "timestamp",
    "run_id",
    "actor",
    "claim_content",
    "claim_content_hash",
    "retraction_expectation",
    "verifier_result",
)


# === Source-type → retraction_expectation pinning ===========================
# Declared once in the spec, NOT asserted per leaf. Describes expectation,
# not current status.
SOURCE_TYPE_RETRACTION: dict[str, str] = {
    "roc-cold-read": "high",
    # everything else → 'normal' (default)
}


def default_retraction_for(source_type: Optional[str]) -> str:
    return SOURCE_TYPE_RETRACTION.get(source_type or "", "normal")


# === Hashing + canonicalization =============================================


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def short_hash(s: str) -> str:
    """16-hex prefix, the convention used everywhere in the substrate."""
    return sha256_hex(s)[:16]


def canonicalize_claim(s: str) -> str:
    """C1 — normalize claim text before hashing, storing, or keying.

    CRLF/CR become LF, trailing whitespace is stripped from each line, and
    the whole string is stripped. Without this, ``'claim'`` and
    ``'claim   '`` produced different hashes and different idempotency
    keys, so trivially-different copies of one claim became separate
    records in an append-only ledger.
    """
    if s is None:
        return ""
    unified = s.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in unified.split("\n")).strip()


def intake_idempotency_key(
    source_path: str, line_start: int, claim_content: str
) -> str:
    return short_hash(
        canonicalize_claim(f"{source_path}:{line_start}:{claim_content}")
    )


def retrieval_idempotency_key(
    answer_text: str, injected_leaf_ids: list, tree_root: str
) -> str:
    """Identity of a retrieval record.

    Leaf ids are SORTED, so a benign reindex that merely permuted
    equal-scoring leaves does not mint a new record for a byte-identical
    answer over the same leaf set.

    Consequence worth knowing: two retrievals that differ ONLY in rank
    collapse to one record_id. ``record_id`` is therefore an idempotency
    key, not a unique retrieval-event id. Rank is preserved separately, in
    ``RetrievalProvenance.injected_leaf_ids``, which is stored in rank
    order — it is NOT recoverable from ``answer_text_hash``, because two
    leaves with identical content produce a byte-identical answer under
    either ordering.
    """
    joined = ",".join(sorted(injected_leaf_ids or []))
    return short_hash(f"{answer_text}:{joined}:{tree_root}")


def apply_redactions(text: str, patterns: list) -> str:
    """C3 — replace every match of every pattern with ``[REDACTED]``.

    Raises ValueError on an uncompilable pattern: a redaction rule that
    silently fails to apply is worse than no rule, because the ledger is
    append-only and the leak is permanent.
    """
    out = text
    for pattern in patterns or []:
        try:
            compiled = re.compile(pattern)
        except re.error as e:
            raise ValueError(
                f"redact_paths contains an invalid regex {pattern!r}: {e}"
            ) from e
        out = compiled.sub(REDACTION_PLACEHOLDER, out)
    return out


# === VerifierResult (common) ================================================


@dataclass
class VerifierResult:
    status: str  # 'pass' | 'fail' | 'skipped'
    method: str  # see VERIFIER_METHODS
    notes: str = ""

    def __post_init__(self) -> None:
        if self.status not in VERIFIER_STATUSES:
            raise ValueError(
                f"verifier_result.status must be one of {VERIFIER_STATUSES}, "
                f"got {self.status!r}"
            )
        if self.method not in VERIFIER_METHODS:
            raise ValueError(
                f"verifier_result.method must be one of {VERIFIER_METHODS}, "
                f"got {self.method!r}"
            )
        # R3 — a 'pass' with no method was the tell for an assertion bypass.
        if self.status == "pass" and self.method == "none":
            raise ValueError(
                "verifier_result status='pass' with method='none' is illegal "
                "(R3): a pass must name the check that produced it"
            )


# === Direction-specific blocks ==============================================


@dataclass
class IntakeProvenance:
    source_path: str
    source_line_start: int
    source_line_end: int
    source_type: str
    source_label: str
    parser_version: str
    redact_paths: list = field(default_factory=list)
    producer_model: Optional[str] = None
    target_branch: Optional[str] = None
    target_confidence: Optional[float] = None
    conflict_policy: str = "keep-both"
    extras: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(
                f"intake.source_type must be one of {SOURCE_TYPES}, "
                f"got {self.source_type!r}"
            )
        if self.source_label not in SOURCE_LABELS:
            raise ValueError(
                f"intake.source_label must be one of {SOURCE_LABELS}, "
                f"got {self.source_label!r}"
            )
        if self.conflict_policy not in CONFLICT_POLICIES:
            raise ValueError(
                f"intake.conflict_policy must be one of {CONFLICT_POLICIES}, "
                f"got {self.conflict_policy!r}"
            )
        if self.target_confidence is not None and not (
            0.0 <= self.target_confidence <= 1.0
        ):
            raise ValueError(
                f"intake.target_confidence must be in [0.0, 1.0], "
                f"got {self.target_confidence!r}"
            )
        # C3 — fail loudly on a pattern that would never apply.
        for pattern in self.redact_paths or []:
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(
                    f"intake.redact_paths contains an invalid regex "
                    f"{pattern!r}: {e}"
                ) from e


@dataclass
class RetrievalProvenance:
    sink: str
    answer_text: str
    answer_text_hash: str
    injected_leaf_ids: list
    leaf_content_hashes: dict
    re_verification: dict
    tree_root_at_trace: str
    retractions_applied: list = field(default_factory=list)
    producer_model: Optional[str] = None
    extras: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.sink:
            raise ValueError("retrieval.sink must be non-empty")
        if not self.tree_root_at_trace:
            raise ValueError(
                "retrieval.tree_root_at_trace must be non-empty "
                "(it anchors the trace to a tree state)"
            )

        keys_h = set(self.leaf_content_hashes.keys())
        keys_r = set(self.re_verification.keys())
        if keys_h != keys_r:
            raise ValueError(
                "retrieval.leaf_content_hashes and re_verification must cover "
                f"the same set: hash-only={keys_h - keys_r}, "
                f"verif-only={keys_r - keys_h}"
            )

        injected = set(self.injected_leaf_ids)
        retracted = set(self.retractions_applied)

        # R1 — a retracted leaf was filtered OUT; it is never injected.
        overlap = injected & retracted
        if overlap:
            raise ValueError(
                "retrieval.injected_leaf_ids and retractions_applied must be "
                f"disjoint (R1); both contain {sorted(overlap)}. A retracted "
                "leaf is filtered out of the answer, never fed into it."
            )

        # R1 — every injected leaf carries a content hash. In v0.1 a leaf
        # listed in both sets could skip the verification map entirely.
        uncovered = injected - keys_h
        if uncovered:
            raise ValueError(
                "every leaf in retrieval.injected_leaf_ids needs a "
                f"leaf_content_hashes entry (R1); missing {sorted(uncovered)}"
            )

        for leaf_id, status in self.re_verification.items():
            if status not in RE_VERIFICATION_STATUSES:
                raise ValueError(
                    f"retrieval.re_verification[{leaf_id}] must be one of "
                    f"{RE_VERIFICATION_STATUSES}, got {status!r}"
                )


def _build_block(cls, raw):
    """Construct a nested block, routing unknown keys into its ``extras``.

    V1 applies to the blocks too: an additive v0.3 field on a retrieval or
    intake block must round-trip through a v0.2 reader rather than raising
    TypeError.
    """
    if raw is None or isinstance(raw, cls):
        return raw
    if not isinstance(raw, dict):
        raise ValueError(
            f"{cls.__name__} block must be a dict, got {type(raw).__name__}"
        )
    raw = dict(raw)
    known = set(cls.__dataclass_fields__)
    extras = raw.pop("extras", None) or {}
    for key in [k for k in raw if k not in known]:
        extras[key] = raw.pop(key)
    return cls(extras=extras, **raw)


def classify_leaf_re_verification(
    *,
    leaf_id: str,
    recorded_hash: str,
    current_hash: Optional[str],
    is_pruned: bool = False,
    is_superseded: bool = False,
    synapses_loaded: bool = False,
) -> str:
    """V2 — classify one leaf's re_verification status.

    Precedence, highest first:

      1. ``missing``   — the leaf cannot be found in the tree now.
      2. ``mismatch``  — found, but the content hash drifted from what the
                         trace recorded.
      3. ``retracted`` — content matches, but the leaf has been withdrawn
                         (soft-pruned) or superseded. Lifecycle-level.
      4. ``pass``      — found, content matches, no lifecycle signal.

    Integrity outranks lifecycle: hiding a real content mutation under a
    "withdrawn" label would let a drift event read as a quiet lifecycle
    note. So a leaf that is BOTH pruned and drifted reads ``mismatch``.
    The reverse is the safer failure — the drift is the actionable alarm,
    and the withdrawal is a lifecycle fact recoverable from the leaf.

    ``missing`` and ``mismatch`` cannot co-occur: with no current hash
    there is nothing to compare.

    CAVEAT — supersession is best-effort. It is honoured only when
    ``synapses_loaded=True``. PCIS's ``data/synapses.json`` may be absent,
    in which case ``load_synapses()`` returns an empty graph and every
    supersession query answers "no" — so a superseded leaf reads ``pass``.
    That is absence of evidence, not evidence of absence. Soft-prune
    detection has no such gap and is unconditional.
    """
    del leaf_id  # accepted for diagnostic clarity at call sites
    if current_hash is None:
        return "missing"
    if recorded_hash != current_hash:
        return "mismatch"
    if is_pruned:
        return "retracted"
    if is_superseded and synapses_loaded:
        return "retracted"
    return "pass"


def derive_verifier_result(retrieval: "RetrievalProvenance") -> VerifierResult:
    """R3 — compute the aggregate from the per-leaf map.

    The per-leaf map is the source of truth for a retrieval record; the
    top-level status is only a summary of it. In v0.1 an "aggregate green
    over per-leaf red" record was legal, so the summary could contradict
    the evidence it summarized.

    R2 — an empty trace is 'skipped', never 'pass'.

    Any non-``pass`` leaf — drifted, gone, or withdrawn — makes the
    aggregate ``fail``. A withdrawn claim that fed an answer is not a clean
    pass, even though its hash still matches.
    """
    if not retrieval.injected_leaf_ids:
        return VerifierResult(
            status="skipped", method="derived", notes="empty trace (R2)"
        )

    statuses = list(retrieval.re_verification.values())
    bad = sorted({s for s in statuses if s != "pass"})
    if bad:
        return VerifierResult(
            status="fail",
            method="derived",
            notes=f"per-leaf non-pass: {bad} of {len(statuses)}",
        )
    return VerifierResult(
        status="pass",
        method="derived",
        notes=f"{len(statuses)} cited leaf/leaves all pass",
    )


# === Top-level ProvenanceRecord =============================================


@dataclass
class ProvenanceRecord:
    record_id: str
    record_kind: str
    timestamp: str
    run_id: str
    actor: str
    claim_content: str
    claim_content_hash: str
    retraction_expectation: str
    verifier_result: VerifierResult
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    intake: Optional[IntakeProvenance] = None
    retrieval: Optional[RetrievalProvenance] = None
    extras: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.record_kind not in RECORD_KINDS:
            raise ValueError(
                f"record_kind must be one of {RECORD_KINDS}, "
                f"got {self.record_kind!r}"
            )
        if self.actor not in ACTORS:
            raise ValueError(f"actor must be one of {ACTORS}, got {self.actor!r}")
        if self.retraction_expectation not in RETRACTION_EXPECTATIONS:
            raise ValueError(
                f"retraction_expectation must be one of "
                f"{RETRACTION_EXPECTATIONS}, got {self.retraction_expectation!r}"
            )
        if not isinstance(self.verifier_result, VerifierResult):
            raise ValueError(
                "verifier_result must be a VerifierResult, got "
                f"{type(self.verifier_result).__name__}"
            )

        # C1/C2 — canonicalize, then require non-empty.
        self.claim_content = canonicalize_claim(self.claim_content)
        if not self.claim_content:
            raise ValueError(
                "claim_content must be non-empty after canonicalization (C2)"
            )
        self.claim_content_hash = sha256_hex(self.claim_content)

        # Direction discriminator.
        if self.record_kind == "intake":
            if self.intake is None:
                raise ValueError(
                    "record_kind='intake' requires the intake block"
                )
            if self.retrieval is not None:
                raise ValueError(
                    "record_kind='intake' must NOT carry a retrieval block"
                )
        elif self.record_kind == "retrieval":
            if self.retrieval is None:
                raise ValueError(
                    "record_kind='retrieval' requires the retrieval block"
                )
            if self.intake is not None:
                raise ValueError(
                    "record_kind='retrieval' must NOT carry an intake block"
                )
            # R3 — the aggregate is computed, never asserted, for retrieval.
            self.verifier_result = derive_verifier_result(self.retrieval)

    # === Serialization ===

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        """Canonical JSON, matching core/events.py:73-77 so a provenance line
        hashes and sorts the same way as every other PCIS journal line."""
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @classmethod
    def from_dict(cls, d: dict) -> "ProvenanceRecord":
        """R4 — reject malformed lines. V1 — keep unknown fields in extras.

        A missing required field raises ValueError and constructs nothing.
        In v0.1 a line without ``verifier_result`` deserialized to None and
        silently skipped every downstream check, permanently, because the
        ledger is append-only.
        """
        if not isinstance(d, dict):
            raise ValueError(f"record must be a dict, got {type(d).__name__}")
        d = dict(d)

        missing = [f for f in REQUIRED_FIELDS if f not in d]
        if missing:
            raise ValueError(
                f"malformed provenance record — missing required field(s): "
                f"{', '.join(missing)} (R4)"
            )

        v = d.pop("verifier_result")
        if v is None:
            raise ValueError(
                "verifier_result must not be null (R4) — a null aggregate "
                "skips every downstream check"
            )
        verifier = v if isinstance(v, VerifierResult) else VerifierResult(**v)

        intake_obj = _build_block(IntakeProvenance, d.pop("intake", None))
        retrieval_obj = _build_block(
            RetrievalProvenance, d.pop("retrieval", None)
        )

        extras = d.pop("extras", None) or {}
        known = {f for f in cls.__dataclass_fields__}
        # V1 — anything this version does not know about round-trips in extras
        # instead of raising TypeError, so additive v0.3 fields survive.
        for key in [k for k in d if k not in known]:
            extras[key] = d.pop(key)

        return cls(
            verifier_result=verifier,
            intake=intake_obj,
            retrieval=retrieval_obj,
            extras=extras,
            **d,
        )

    @classmethod
    def from_json(cls, s: str) -> "ProvenanceRecord":
        return cls.from_dict(json.loads(s))


# === Producer-certifies-self invariant ======================================


def assert_self_certification_blocked(
    actor: str, claim_producer: str, status: str
) -> None:
    """The producer of a claim cannot elevate its own verdict to 'pass'.

    Raises PermissionError on a forbidden self-certification; returns None
    when the action is allowed.

    NOT WIRED into ProvenanceRecord for retrieval records in v0.2: a
    retrieval trace is written by the same code path that selected the
    leaves, and ``claim_producer`` is not a field on the record. Callers
    that can identify the producer should call this explicitly.
    """
    if actor == claim_producer and status == "pass":
        raise PermissionError(
            f"self-certification forbidden: actor={actor!r} produced the "
            f"claim; verifier_result.status='pass' requires external "
            f"corroboration"
        )
