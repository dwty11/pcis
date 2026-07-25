"""test_provenance_schema.py — PCIS's ProvenanceRecord v0.2 implementation.

WHY THIS IS RE-IMPLEMENTED RATHER THAN IMPORTED
===============================================
The contract is shared with the upstream substrate, but the code is
deliberately NOT. Importing the upstream ``provenance_schema`` would
re-couple the two codebases — exactly what the sanitization removed. The two
implementations are kept in sync by ``tests/test_schema_parity.py``,
which asserts this module against the v0.2 contract rather than sharing
a line of code with it.

Spec: provenance-schema-v0.2-2026-07-25.md, held in the upstream
workspace. Set PCIS_SIBLING_WORKSPACE to point the parity tests at it.

These tests are written against the CHANGELOG's rule ids (R1-R4, V1-V2,
C1-C3) so a reader can trace each assertion to the clause it enforces.
"""

from __future__ import annotations

import hashlib
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, _ROOT)


def _retrieval(**over):
    """A minimal valid retrieval block; override any field."""
    from provenance import RetrievalProvenance

    kwargs = dict(
        sink="pcis.retrieval-trace",
        answer_text="the root moves on every commit",
        answer_text_hash=hashlib.sha256(
            b"the root moves on every commit"
        ).hexdigest(),
        injected_leaf_ids=["L-1"],
        leaf_content_hashes={"L-1": "h1"},
        re_verification={"L-1": "pass"},
        tree_root_at_trace="a" * 64,
        retractions_applied=[],
    )
    kwargs.update(over)
    return RetrievalProvenance(**kwargs)


def _record(**over):
    from provenance import ProvenanceRecord, VerifierResult, sha256_hex

    claim = over.pop("claim_content", "a claim worth recording")
    kwargs = dict(
        record_id="0" * 16,
        record_kind="retrieval",
        timestamp="2026-07-25T15:30:00+03:00",
        run_id="trace-2026-07-25-001",
        actor="cc",
        claim_content=claim,
        claim_content_hash=sha256_hex(claim),
        retraction_expectation="normal",
        verifier_result=VerifierResult(status="pass", method="content_hash"),
    )
    if "retrieval" not in over and "intake" not in over:
        kwargs["retrieval"] = _retrieval()
    kwargs.update(over)
    return ProvenanceRecord(**kwargs)


class TestC1ClaimCanonicalization:
    """C1 — canonicalize_claim: CRLF/CR -> LF, rstrip each line, strip overall."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("claim   ", "claim"),
            ("  claim", "claim"),
            ("a\r\nb", "a\nb"),
            ("a\rb", "a\nb"),
            ("a   \nb\t\n", "a\nb"),
            ("\n\nclaim\n\n", "claim"),
        ],
    )
    def test_canonicalize(self, raw, expected):
        from provenance import canonicalize_claim

        assert canonicalize_claim(raw) == expected

    def test_whitespace_variants_hash_identically(self):
        """The v0.1 bug C1 fixes: 'claim' and 'claim   ' hashed differently."""
        from provenance import canonicalize_claim, sha256_hex

        a = sha256_hex(canonicalize_claim("claim"))
        b = sha256_hex(canonicalize_claim("claim   "))
        c = sha256_hex(canonicalize_claim("claim\r\n"))
        assert a == b == c

    def test_record_stores_canonicalized_claim(self):
        rec = _record(claim_content="a claim worth recording   \r\n")
        assert rec.claim_content == "a claim worth recording"

    def test_record_claim_hash_matches_canonical_text(self):
        from provenance import sha256_hex

        rec = _record(claim_content="  spaced claim  ")
        assert rec.claim_content_hash == sha256_hex(rec.claim_content)


class TestC2NonEmptyClaim:
    """C2 — claim_content must be non-empty post-canonicalization."""

    @pytest.mark.parametrize("blank", ["", "   ", "\r\n", "\n\n  \t "])
    def test_blank_claim_rejected(self, blank):
        with pytest.raises(ValueError, match="claim_content"):
            _record(claim_content=blank)


class TestR1RetractionsDisjointFromInjected:
    """R1 — a retracted leaf is filtered out, never injected."""

    def test_overlap_rejected(self):
        with pytest.raises(ValueError, match="disjoint"):
            _retrieval(
                injected_leaf_ids=["L-1", "L-2"],
                leaf_content_hashes={"L-1": "h1", "L-2": "h2"},
                re_verification={"L-1": "pass", "L-2": "pass"},
                retractions_applied=["L-2"],
            )

    def test_every_injected_leaf_needs_a_content_hash(self):
        """The v0.1 hole: a leaf could skip the verification map entirely."""
        with pytest.raises(ValueError):
            _retrieval(
                injected_leaf_ids=["L-1", "L-2"],
                leaf_content_hashes={"L-1": "h1"},
                re_verification={"L-1": "pass"},
                retractions_applied=["L-2"],
            )

    def test_disjoint_retraction_accepted(self):
        block = _retrieval(
            injected_leaf_ids=["L-1"],
            leaf_content_hashes={"L-1": "h1"},
            re_verification={"L-1": "pass"},
            retractions_applied=["L-9"],
        )
        assert block.retractions_applied == ["L-9"]

    def test_hash_and_verification_keys_must_match(self):
        with pytest.raises(ValueError):
            _retrieval(
                injected_leaf_ids=["L-1"],
                leaf_content_hashes={"L-1": "h1"},
                re_verification={"L-1": "pass", "L-2": "pass"},
            )


class TestR2EmptyTraceIsSkipped:
    """R2 — an empty trace is 'skipped', never 'pass'."""

    def test_empty_trace_forces_skipped(self):
        rec = _record(
            retrieval=_retrieval(
                injected_leaf_ids=[], leaf_content_hashes={}, re_verification={}
            )
        )
        assert rec.verifier_result.status == "skipped"
        assert "empty trace (R2)" in rec.verifier_result.notes

    def test_empty_trace_is_not_pass_even_when_asserted(self):
        from provenance import VerifierResult

        rec = _record(
            verifier_result=VerifierResult(status="pass", method="content_hash"),
            retrieval=_retrieval(
                injected_leaf_ids=[], leaf_content_hashes={}, re_verification={}
            ),
        )
        assert rec.verifier_result.status == "skipped"


class TestR3AggregateIsDerived:
    """R3 — for retrieval, verifier_result is computed from re_verification."""

    def test_all_pass_derives_pass(self):
        rec = _record()
        assert rec.verifier_result.status == "pass"
        assert rec.verifier_result.method == "derived"

    @pytest.mark.parametrize("bad", ["mismatch", "missing"])
    def test_any_bad_leaf_derives_fail(self, bad):
        rec = _record(
            retrieval=_retrieval(
                injected_leaf_ids=["L-1", "L-2"],
                leaf_content_hashes={"L-1": "h1", "L-2": "h2"},
                re_verification={"L-1": "pass", "L-2": bad},
            )
        )
        assert rec.verifier_result.status == "fail"

    def test_user_asserted_aggregate_is_overridden(self):
        """'Aggregate green over per-leaf red' was legal in v0.1."""
        from provenance import VerifierResult

        rec = _record(
            verifier_result=VerifierResult(status="pass", method="full_text"),
            retrieval=_retrieval(
                injected_leaf_ids=["L-1"],
                leaf_content_hashes={"L-1": "h1"},
                re_verification={"L-1": "mismatch"},
            ),
        )
        assert rec.verifier_result.status == "fail"
        assert rec.verifier_result.method == "derived"

    def test_intake_keeps_user_set_verifier_result(self):
        """R3 explicitly does NOT apply to intake."""
        from provenance import VerifierResult

        rec = _record(
            record_kind="intake",
            intake=_intake(),
            retrieval=None,
            verifier_result=VerifierResult(
                status="pass", method="line_match", notes="quote verified"
            ),
        )
        assert rec.verifier_result.status == "pass"
        assert rec.verifier_result.method == "line_match"

    def test_pass_with_method_none_is_illegal(self):
        from provenance import VerifierResult

        with pytest.raises(ValueError):
            VerifierResult(status="pass", method="none")

    def test_skipped_with_method_none_is_legal(self):
        from provenance import VerifierResult

        assert VerifierResult(status="skipped", method="none").method == "none"


def _intake(**over):
    from provenance import IntakeProvenance

    kwargs = dict(
        source_path="drafts/handoff-2026-07-25.md",
        source_line_start=17,
        source_line_end=23,
        source_type="handoff",
        source_label="PROVEN",
        parser_version="handoff_parser_v0.1",
    )
    kwargs.update(over)
    return IntakeProvenance(**kwargs)


class TestC3RedactPaths:
    """C3 — redact_paths on intake records."""

    def test_defaults_to_empty_list(self):
        assert _intake().redact_paths == []

    # Fixtures are deliberately synthetic. C3 exists because a real
    # employer reference plus an append-only ledger is a permanent leak —
    # so the test for it must not itself commit a real name to a public
    # repo. Same regex classes (a literal token, an international phone
    # shape), none of the real referents.
    def test_accepts_patterns(self):
        block = _intake(redact_paths=[r"ExampleCorp", r"\+1\d{10}"])
        assert block.redact_paths == [r"ExampleCorp", r"\+1\d{10}"]

    def test_invalid_regex_is_flagged_not_silently_dropped(self):
        with pytest.raises(ValueError, match="redact_paths"):
            _intake(redact_paths=["([unclosed"])

    def test_apply_redactions_replaces_matches(self):
        from provenance import apply_redactions

        out = apply_redactions(
            "met Testperson at ExampleCorp on +15550001111",
            [r"ExampleCorp", r"\+1\d{10}"],
        )
        assert "ExampleCorp" not in out
        assert "+15550001111" not in out
        assert out.count("[REDACTED]") == 2


class TestR4RequiredFieldsInFromDict:
    """R4 — a malformed ledger line must not construct a record."""

    REQUIRED = [
        "record_id", "record_kind", "timestamp", "run_id", "actor",
        "claim_content", "claim_content_hash", "retraction_expectation",
        "verifier_result",
    ]

    @pytest.mark.parametrize("field", REQUIRED)
    def test_missing_required_field_raises_value_error(self, field):
        from provenance import ProvenanceRecord

        d = _record().to_dict()
        d.pop(field)
        with pytest.raises(ValueError, match=field):
            ProvenanceRecord.from_dict(d)

    def test_null_verifier_result_raises(self):
        """v0.1 accepted this and skipped every downstream check."""
        from provenance import ProvenanceRecord

        d = _record().to_dict()
        d["verifier_result"] = None
        with pytest.raises(ValueError):
            ProvenanceRecord.from_dict(d)


class TestV1ForwardCompat:
    """V1 — unknown fields land in extras, never TypeError."""

    def test_unknown_field_does_not_raise(self):
        from provenance import ProvenanceRecord

        d = _record().to_dict()
        d["schema_version"] = "0.3"
        rec = ProvenanceRecord.from_dict(d)
        assert rec.extras["schema_version"] == "0.3"

    def test_unknown_fields_round_trip(self):
        from provenance import ProvenanceRecord

        d = _record().to_dict()
        d["a_v03_field"] = {"nested": [1, 2]}
        rec = ProvenanceRecord.from_dict(d)
        assert ProvenanceRecord.from_dict(rec.to_dict()).extras["a_v03_field"] == {
            "nested": [1, 2]
        }

    def test_round_trip_is_stable(self):
        from provenance import ProvenanceRecord

        rec = _record()
        assert ProvenanceRecord.from_json(rec.to_json()).to_json() == rec.to_json()


class TestDiscriminator:
    def test_both_blocks_rejected(self):
        with pytest.raises(ValueError):
            _record(intake=_intake(), retrieval=_retrieval())

    def test_retrieval_kind_requires_retrieval_block(self):
        with pytest.raises(ValueError):
            _record(retrieval=None)

    def test_intake_kind_rejects_retrieval_block(self):
        with pytest.raises(ValueError):
            _record(record_kind="intake", retrieval=_retrieval())


class TestIdempotencyKeys:
    def test_retrieval_key_sorts_leaf_ids(self):
        from provenance import retrieval_idempotency_key

        assert retrieval_idempotency_key("ans", ["L-2", "L-1"], "root") == \
            retrieval_idempotency_key("ans", ["L-1", "L-2"], "root")

    def test_retrieval_key_matches_spec_formula(self):
        from provenance import retrieval_idempotency_key

        expected = hashlib.sha256(
            "ans:L-1,L-2:root".encode("utf-8")
        ).hexdigest()[:16]
        assert retrieval_idempotency_key("ans", ["L-2", "L-1"], "root") == expected

    def test_retrieval_key_changes_with_root(self):
        from provenance import retrieval_idempotency_key

        assert retrieval_idempotency_key("ans", ["L-1"], "r1") != \
            retrieval_idempotency_key("ans", ["L-1"], "r2")

    def test_intake_key_is_canonicalized(self):
        """C1 — whitespace-variant duplicates collide to one record."""
        from provenance import intake_idempotency_key

        assert intake_idempotency_key("a.md", 1, "claim") == \
            intake_idempotency_key("a.md", 1, "claim   ")

    def test_keys_are_16_hex(self):
        from provenance import intake_idempotency_key, retrieval_idempotency_key

        for key in (
            intake_idempotency_key("a.md", 1, "c"),
            retrieval_idempotency_key("a", ["L-1"], "r"),
        ):
            assert len(key) == 16
            int(key, 16)


class TestEnumsAndPinning:
    def test_enum_members(self):
        import provenance as p

        assert p.RECORD_KINDS == ("intake", "retrieval")
        assert p.ACTORS == ("architect", "cc", "roc", "gardener", "user")
        assert p.RE_VERIFICATION_STATUSES == (
            "pass", "mismatch", "missing", "retracted",
        )
        assert p.VERIFIER_STATUSES == ("pass", "fail", "skipped")
        assert "derived" in p.VERIFIER_METHODS
        assert p.SCHEMA_VERSION == "0.2"

    def test_unknown_re_verification_value_rejected(self):
        with pytest.raises(ValueError):
            _retrieval(re_verification={"L-1": "probably-fine"})

    def test_bad_actor_rejected(self):
        with pytest.raises(ValueError):
            _record(actor="a-stranger")

    def test_source_type_pinning(self):
        from provenance import default_retraction_for

        assert default_retraction_for("roc-cold-read") == "high"
        assert default_retraction_for("handoff") == "normal"
        assert default_retraction_for(None) == "normal"


class TestSelfCertification:
    def test_producer_cannot_certify_itself(self):
        from provenance import assert_self_certification_blocked

        with pytest.raises(PermissionError):
            assert_self_certification_blocked(
                actor="cc", claim_producer="cc", status="pass"
            )

    def test_other_actor_may_pass(self):
        from provenance import assert_self_certification_blocked

        assert assert_self_certification_blocked(
            actor="cc", claim_producer="roc", status="pass"
        ) is None

    def test_self_certified_non_pass_is_allowed(self):
        from provenance import assert_self_certification_blocked

        assert assert_self_certification_blocked(
            actor="cc", claim_producer="cc", status="fail"
        ) is None


class TestV2RetractedStatus:
    """V2 — 'retracted' joins the per-leaf vocabulary."""

    def test_retracted_is_a_valid_wire_value(self):
        block = _retrieval(re_verification={"L-1": "retracted"})
        assert block.re_verification == {"L-1": "retracted"}

    def test_retracted_leaf_derives_fail(self):
        """A withdrawn claim that fed an answer is not a clean pass."""
        rec = _record(retrieval=_retrieval(re_verification={"L-1": "retracted"}))
        assert rec.verifier_result.status == "fail"
        assert rec.verifier_result.method == "derived"


class TestV2LeafClassificationPrecedence:
    """V2 — precedence when signals collide: mismatch > missing > retracted
    > pass. Integrity outranks lifecycle, because hiding a real content
    mutation under a lifecycle label would let it read as a quiet signal.

    CAVEAT, load-bearing: 'retracted' is honest for soft-prune, but
    supersession is BEST-EFFORT — it is computed only when the synapse graph
    was actually loaded. With synapses absent, a superseded leaf reads
    'pass'. That is absence of evidence, not evidence of absence.
    """

    def _classify(self, **kw):
        from provenance import classify_leaf_re_verification

        base = dict(
            leaf_id="L-1", recorded_hash="h1", current_hash="h1",
            is_pruned=False, is_superseded=False, synapses_loaded=False,
        )
        base.update(kw)
        return classify_leaf_re_verification(**base)

    def test_unchanged_live_leaf_passes(self):
        assert self._classify() == "pass"

    def test_absent_leaf_is_missing(self):
        assert self._classify(current_hash=None) == "missing"

    def test_drifted_leaf_is_mismatch(self):
        assert self._classify(current_hash="h2") == "mismatch"

    def test_soft_pruned_leaf_is_retracted(self):
        assert self._classify(is_pruned=True) == "retracted"

    def test_pruned_AND_drifted_reads_mismatch(self):
        """The precedence ruling: integrity outranks lifecycle."""
        assert self._classify(current_hash="h2", is_pruned=True) == "mismatch"

    def test_absent_AND_pruned_reads_missing(self):
        assert self._classify(current_hash=None, is_pruned=True) == "missing"

    def test_superseded_is_retracted_only_when_synapses_loaded(self):
        assert self._classify(is_superseded=True, synapses_loaded=True) == "retracted"

    def test_superseded_reads_pass_when_synapses_absent(self):
        """The vacuous-supersession caveat, asserted so it cannot be
        mistaken for coverage."""
        assert self._classify(is_superseded=True, synapses_loaded=False) == "pass"

    def test_returns_only_known_statuses(self):
        import provenance as p

        for kw in (
            {}, {"current_hash": None}, {"current_hash": "h2"},
            {"is_pruned": True}, {"is_superseded": True, "synapses_loaded": True},
        ):
            assert self._classify(**kw) in p.RE_VERIFICATION_STATUSES


class TestV1BlockLevelExtras:
    """V1 — unknown fields round-trip on the nested blocks too, not just
    the top level."""

    def test_retrieval_block_absorbs_unknown_fields(self):
        from provenance import ProvenanceRecord

        d = _record().to_dict()
        d["retrieval"]["a_v03_field"] = 7
        rec = ProvenanceRecord.from_dict(d)
        assert rec.retrieval.extras["a_v03_field"] == 7

    def test_intake_block_absorbs_unknown_fields(self):
        from provenance import ProvenanceRecord

        d = _record(record_kind="intake", intake=_intake(), retrieval=None).to_dict()
        d["intake"]["a_v03_field"] = 7
        rec = ProvenanceRecord.from_dict(d)
        assert rec.intake.extras["a_v03_field"] == 7


class TestParityLockedAggregateShape:
    """The aggregate's status+method are parity-locked against the other
    implementation. Notes prose is deliberately NOT parity-locked."""

    def test_empty_trace_method_is_derived(self):
        rec = _record(
            retrieval=_retrieval(
                injected_leaf_ids=[], leaf_content_hashes={}, re_verification={}
            )
        )
        assert (rec.verifier_result.status, rec.verifier_result.method) == (
            "skipped", "derived",
        )
