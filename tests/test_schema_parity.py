"""test_schema_parity.py — keeps PCIS's ProvenanceRecord in sync with the
shared v0.2 contract WITHOUT sharing code with the other implementation.

WHY THIS TEST EXISTS
====================
The ProvenanceRecord contract is implemented twice: here in PCIS
(``core/provenance.py``) and in OpenClaw (``provenance_schema.py``). That
duplication is deliberate — importing across the two codebases would
re-couple them, which is exactly what PCIS's sanitization removed.

But deleting the import also deleted the enforcement. Before, a drifted
field name was an ``AttributeError`` at runtime; the interpreter held the
two sides together. Now nothing does except this file. That raises the
stakes on a silent pass: a version of this test that reports green while
the implementations have diverged leaves PCIS with neither the coupling nor
the check — strictly worse than the import it replaced, because a green
suite is read as evidence.

Unlike ``test_crypto_parity.py``, this CANNOT be a byte-identity test. The
two implementations are deliberately different code. So parity is asserted
three ways, with three different failure modes:

  1. ``TestSchemaParityVsSiblingAST`` — highest fidelity, compares this
     module against the sibling's declarations by parsing its source (no
     import). SKIPS when the sibling is absent.
  2. ``TestSchemaParityVsSpecFieldNames`` — the only check that catches BOTH
     implementations drifting together, since it reads the human spec.
     Deliberately narrow: field names and order only (see the class
     docstring for why nothing else in the markdown is trustworthy).
     SKIPS when the spec is absent.
  3. ``TestSchemaContractVectors`` — NEVER SKIPS. Pins the contract as data
     that travels with PCIS.

WHY CLASS 3 IS NOT OPTIONAL
===========================
``.github/workflows/ci.yml`` runs ``pytest tests/ -v`` on ubuntu-latest,
and ``WHIS_WORKSPACE`` is set nowhere in this repo. Neither the sibling
module nor the spec markdown exists on a CI runner. So on every push and
every PR, classes 1 and 2 skip and the suite goes green having checked
nothing. Class 3 is what makes "CI is green" carry information about the
contract. It also pins the two idempotency formulas, which are unreachable
by both other mechanisms: the spec states them as prose pseudocode that is
not valid Python, and the sibling implements them as an f-string, so there
is no textual or structural comparison available — only behaviour.

PATH RESOLUTION
===============
Reuses ``WHIS_WORKSPACE``, the same switch as ``test_crypto_parity.py``, so
one variable enables the whole parity family. If set, ONLY that path is
tried — an operator who pointed us somewhere deserves a skip, not a silent
fallback to the default.

The spec filename is PINNED, never globbed. A v0.2 parity test must not
silently start validating against a v0.3 file; a version bump should
require a human editing a constant.

SKIP vs FAIL
============
Absent artifact → skip, loudly, naming the resolved absolute path.
Present artifact that disagrees → fail. A present-but-unparseable sibling
is a FAILURE, not a skip: a syntactically broken contract module is a real
finding. A named target that has gone missing (a renamed constant) is also
a failure, never a skip — otherwise a rename silently unasserts it.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, _ROOT)

SPEC_RELPATH = "drafts/provenance-schema-v0.2-2026-07-25.md"
SIBLING_RELPATH = "provenance_schema.py"

# ---------------------------------------------------------------------------
# Path resolution — env var wins outright; no fallback when it is set.
# ---------------------------------------------------------------------------


def _resolve(relpath: str) -> Path | None:
    explicit = os.environ.get("WHIS_WORKSPACE")
    if explicit:
        p = Path(explicit).expanduser() / relpath
        return p if p.exists() else None
    default = Path.home() / ".openclaw" / "workspace" / relpath
    return default if default.exists() else None


def _skip_message(relpath: str) -> str:
    if os.environ.get("WHIS_WORKSPACE"):
        looked = Path(os.environ["WHIS_WORKSPACE"]).expanduser() / relpath
    else:
        looked = Path.home() / ".openclaw" / "workspace" / relpath
    return (
        f"OpenClaw's {relpath} not found (resolved to: {looked}). Set "
        f"WHIS_WORKSPACE=/path/to/openclaw/workspace to enable this class. "
        f"The skip is INTENTIONAL — a silent pass would be worse than no "
        f"test. TestSchemaContractVectors still runs and does not skip."
    )


@pytest.fixture(scope="module")
def sibling_source() -> str | None:
    path = _resolve(SIBLING_RELPATH)
    return path.read_text(encoding="utf-8") if path else None


@pytest.fixture(scope="module")
def spec_text() -> str | None:
    path = _resolve(SPEC_RELPATH)
    return path.read_text(encoding="utf-8") if path else None


# ---------------------------------------------------------------------------
# AST extraction — no import of the sibling, ever.
# ---------------------------------------------------------------------------

DATACLASSES = (
    "ProvenanceRecord",
    "IntakeProvenance",
    "RetrievalProvenance",
    "VerifierResult",
)

PARITY_ENUMS = (
    "RECORD_KINDS",
    "ACTORS",
    "SOURCE_TYPES",
    "SOURCE_LABELS",
    "CONFLICT_POLICIES",
    "RETRACTION_EXPECTATIONS",
    "VERIFIER_STATUSES",
    "VERIFIER_METHODS",
    "RE_VERIFICATION_STATUSES",
)

# Fields the spec's tables legitimately omit, with the reason.
#   intake/retrieval — nested container fields, described in prose (spec
#     "Direction discriminator") rather than listed as rows.
#   extras — V1 forward-compat plumbing; listed in the common table only.
SPEC_OMITS = {
    "ProvenanceRecord": {"intake", "retrieval"},
    "IntakeProvenance": {"extras"},
    "RetrievalProvenance": {"extras"},
    "VerifierResult": set(),
}

SPEC_TABLE_FOR = {
    "ProvenanceRecord": "Common top-level fields",
    "IntakeProvenance": "Intake block",
    "RetrievalProvenance": "Retrieval block",
    "VerifierResult": "VerifierResult",
}


def _parse(source: str, label: str) -> ast.Module:
    try:
        return ast.parse(source)
    except SyntaxError as e:
        pytest.fail(
            f"{label} is present but does not parse: {e}. A syntactically "
            f"broken contract module is a real finding, not an absence — "
            f"this is a FAILURE by design, not a skip."
        )


def _dataclass_fields(source: str, name: str) -> list[str] | None:
    """Ordered field names of a top-level dataclass, from source only.

    Walks both ``AnnAssign`` (``x: int = 1``) and plain ``Assign``; a
    dataclass body is normally all AnnAssign, but do not assume it.
    """
    tree = _parse(source, "sibling module")
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            out = []
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(
                    stmt.target, ast.Name
                ):
                    out.append(stmt.target.id)
                elif isinstance(stmt, ast.Assign):
                    for t in stmt.targets:
                        if isinstance(t, ast.Name):
                            out.append(t.id)
            return out
    return None


def _module_constant(source: str, name: str):
    """Literal value of a top-level constant. Handles AnnAssign as well as
    Assign — SOURCE_TYPE_RETRACTION is annotated ``dict[str, str]``, and an
    Assign-only walk would silently never check it."""
    tree = _parse(source, "sibling module")
    for node in tree.body:
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(
            node.targets[0], ast.Name
        ):
            target, value = node.targets[0].id, node.value
        if target == name and value is not None:
            try:
                return ast.literal_eval(value)
            except ValueError:
                pytest.fail(
                    f"{name} in the sibling is not a literal, so it cannot be "
                    f"compared structurally."
                )
    return None


# ---------------------------------------------------------------------------
# Markdown table extraction — GFM escape aware.
# ---------------------------------------------------------------------------

_SENTINEL = "\x00"


def _split_row(line: str) -> list[str]:
    """Split a GFM table row, honouring backslash-escaped pipes.

    This matters: union types in the spec are written ``'a' \\| 'b'`` inside
    pipe-delimited rows, so a naive ``split('|')`` yields 7 cells where
    there are 3.
    """
    masked = line.replace("\\|", _SENTINEL)
    cells = [c.strip().replace(_SENTINEL, "|") for c in masked.strip().strip("|").split("|")]
    return cells


def _spec_field_names(spec: str, heading_contains: str) -> list[str] | None:
    """Field-name column of the table under the matching ``##`` heading."""
    lines = spec.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("##") and heading_contains.lower() in line.lower():
            start = i
            break
    if start is None:
        return None

    names, in_table = [], False
    for line in lines[start + 1:]:
        if line.startswith("##"):
            break
        if line.strip().startswith("|"):
            cells = _split_row(line)
            if cells[:1] == ["Field"]:
                in_table = True
                continue
            if not in_table:
                continue
            if set(cells[0]) <= {"-", ":"}:
                continue
            m = re.match(r"^`([^`]+)`$", cells[0])
            if m:
                names.append(m.group(1))
        elif in_table and line.strip() == "":
            continue
    return names or None


# ---------------------------------------------------------------------------
# Class 1 — vs the sibling implementation
# ---------------------------------------------------------------------------


class TestSchemaParityVsSiblingAST:
    """PCIS's declarations match the sibling implementation's.

    Compares by parsing the sibling's source — never importing it, so this
    test cannot itself create the coupling it exists to avoid.

    Blind spot, stated so nobody mistakes green here for full parity: the
    sibling's real contract is partly in ``__post_init__``, which AST
    comparison cannot see. PCIS could reproduce every field and enum with
    none of the cross-field validation and this class would stay green.
    That is what ``TestSchemaContractVectors`` is for.
    """

    def test_sibling_resolves(self, sibling_source):
        if sibling_source is None:
            pytest.skip(_skip_message(SIBLING_RELPATH))
        assert sibling_source.strip(), "sibling module resolved but is empty"

    def test_parity_target_lists_are_not_empty(self):
        """An empty parametrize list passes zero cases and reports green."""
        assert len(DATACLASSES) == 4
        assert len(PARITY_ENUMS) == 9

    @pytest.mark.parametrize("name", DATACLASSES)
    def test_dataclass_fields_match_in_order(self, sibling_source, name):
        if sibling_source is None:
            pytest.skip(_skip_message(SIBLING_RELPATH))
        import provenance
        from dataclasses import fields

        theirs = _dataclass_fields(sibling_source, name)
        assert theirs is not None, (
            f"{name} not found in the sibling — either it was renamed or "
            f"DATACLASSES here is stale. This is a FAILURE, not a skip."
        )
        ours = [f.name for f in fields(getattr(provenance, name))]

        # Order matters even though to_json sorts keys: the sibling
        # constructs positionally (e.g. VerifierResult("pass", "none")), so a
        # reorder silently changes what positional construction means.
        assert ours == theirs, (
            f"{name} field list diverged.\n  PCIS:    {ours}\n"
            f"  Sibling: {theirs}\n"
            f"Only-in-PCIS: {set(ours) - set(theirs)}; "
            f"only-in-sibling: {set(theirs) - set(ours)}"
        )

    @pytest.mark.parametrize("name", PARITY_ENUMS)
    def test_enum_members_match(self, sibling_source, name):
        if sibling_source is None:
            pytest.skip(_skip_message(SIBLING_RELPATH))
        import provenance

        theirs = _module_constant(sibling_source, name)
        assert theirs is not None, (
            f"{name} not found in the sibling — renamed, or PARITY_ENUMS is "
            f"stale. FAILURE, not a skip: a lookup that returns nothing must "
            f"never silently unassert an enum."
        )
        ours = getattr(provenance, name, None)
        assert ours is not None, f"PCIS is missing {name}"
        assert tuple(ours) == tuple(theirs), (
            f"{name} diverged.\n  PCIS:    {tuple(ours)}\n  Sibling: {tuple(theirs)}"
        )

    def test_source_type_retraction_pinning_matches(self, sibling_source):
        """Annotated assignment — an Assign-only walk would miss this, and
        the pinning table is the one thing the spec calls normative."""
        if sibling_source is None:
            pytest.skip(_skip_message(SIBLING_RELPATH))
        import provenance

        theirs = _module_constant(sibling_source, "SOURCE_TYPE_RETRACTION")
        assert theirs is not None, "SOURCE_TYPE_RETRACTION not found in sibling"
        assert provenance.SOURCE_TYPE_RETRACTION == theirs

    def test_schema_version_matches(self, sibling_source):
        """Pinned explicitly so a version bump produces ONE legible failure
        that says 'the contract moved', not ten that say 'a field changed'."""
        if sibling_source is None:
            pytest.skip(_skip_message(SIBLING_RELPATH))
        import provenance

        assert _module_constant(sibling_source, "SCHEMA_VERSION") == \
            provenance.SCHEMA_VERSION == "0.2"


# ---------------------------------------------------------------------------
# Class 2 — vs the human spec
# ---------------------------------------------------------------------------


class TestSchemaParityVsSpecFieldNames:
    """PCIS's field names and order match the written contract.

    This is the ONLY check that catches both implementations drifting
    together, because it reads the design rather than the other code.

    DELIBERATELY NARROW — field names and order, nothing else. The Type and
    Description columns are read but NOT asserted, and that is not
    laziness:

      * The Type column disagrees textually with both implementations on
        roughly half its rows — ``enum`` as a bare placeholder carrying no
        members, ``str (16 hex)``, ``str\\|null`` vs ``Optional[str]``,
        ``list[str]`` vs bare ``list``. Normalising needs ~18 hand-written
        mappings, at which point the test asserts its own mapping table
        rather than the spec.
      * The Description column's enum literals cannot be extracted safely:
        one row uses English "or" instead of the ``\\|`` convention, default
        clauses inject duplicate members, the Type column is not a reliable
        is-enum gate, and ``sink``'s "(e.g., `'pcis.retrieval-trace'`)" would
        mint a bogus one-member enum from an EXAMPLE.

    Enum members are covered against the sibling (class 1) and behaviourally
    (class 3). Do not "improve" this class into a brittle type table.
    """

    def test_spec_resolves(self, spec_text):
        if spec_text is None:
            pytest.skip(_skip_message(SPEC_RELPATH))
        assert "ProvenanceRecord v0.2" in spec_text, (
            "resolved spec does not look like the v0.2 contract"
        )

    def test_all_four_tables_are_found(self, spec_text):
        """If a markdown reflow drops a table, the per-table comparisons
        would otherwise pass vacuously against nothing."""
        if spec_text is None:
            pytest.skip(_skip_message(SPEC_RELPATH))
        for name, heading in SPEC_TABLE_FOR.items():
            names = _spec_field_names(spec_text, heading)
            assert names, f"no field table found under a heading matching {heading!r}"
            assert len(names) >= 3, f"{heading} table has only {len(names)} rows"

    @pytest.mark.parametrize("name", DATACLASSES)
    def test_field_names_and_order_match_spec(self, spec_text, name):
        if spec_text is None:
            pytest.skip(_skip_message(SPEC_RELPATH))
        import provenance
        from dataclasses import fields

        spec_names = _spec_field_names(spec_text, SPEC_TABLE_FOR[name])
        assert spec_names, f"no table for {name}"

        ours = [
            f.name
            for f in fields(getattr(provenance, name))
            if f.name not in SPEC_OMITS[name]
        ]
        assert ours == spec_names, (
            f"{name} diverged from the SPEC (not just the sibling — this "
            f"catches both implementations drifting together).\n"
            f"  PCIS (minus {sorted(SPEC_OMITS[name]) or 'nothing'}): {ours}\n"
            f"  Spec: {spec_names}"
        )

    def test_escape_aware_row_split(self):
        """Guards the parser itself: a naive split('|') gives 7 cells here."""
        row = "| `actor` | enum | `'whis' \\| 'cc' \\| 'roc'` |"
        cells = _split_row(row)
        assert len(cells) == 3
        assert cells[0] == "`actor`"
        assert cells[2] == "`'whis' | 'cc' | 'roc'`"


# ---------------------------------------------------------------------------
# Class 3 — behavioural vectors. NEVER SKIPS.
# ---------------------------------------------------------------------------


class TestSchemaContractVectors:
    """The contract as data that travels with PCIS. No skip path.

    Everything here is behaviour that neither AST comparison nor markdown
    parsing can reach: the idempotency formulas, the cross-field invariants,
    and the precedence matrix. These digests were computed against the live
    sibling; if PCIS changes how it builds a preimage, they red.
    """

    # --- idempotency formulas ---------------------------------------------

    def test_intake_key_vector(self):
        from provenance import intake_idempotency_key

        assert intake_idempotency_key("a.md", 1, "c") == "2413f1fb4141145f"

    def test_retrieval_key_vector_proves_sorting(self):
        """Input is deliberately UNSORTED, so this vector pins the sorted()."""
        from provenance import retrieval_idempotency_key

        assert retrieval_idempotency_key("ans", ["L-2", "L-1"], "root0") == \
            "582d79f808afd378"

    def test_retrieval_key_empty_leaf_list(self):
        from provenance import retrieval_idempotency_key

        a = retrieval_idempotency_key("ans", [], "root0")
        b = retrieval_idempotency_key("ans", None, "root0")
        assert a == b and len(a) == 16

    def test_intake_key_is_not_delimiter_safe(self):
        """Documents a REAL weakness rather than asserting it away.

        The preimage is a ':'-joined f-string, so ``('a:1', 2, 'c')`` and
        ``('a', '1:2', 'c')`` both canonicalize to ``a:1:2:c`` and collide.
        That is a genuine flaw. It is pinned here because a well-meant fix
        (length-prefixing the segments) would produce a BETTER formula that
        silently breaks idempotency across the two ledgers — this vector
        turns that into a red test and a conversation, not a silent split.
        """
        from provenance import intake_idempotency_key

        assert intake_idempotency_key("a:1", 2, "c") == \
            intake_idempotency_key("a", "1:2", "c")

    def test_unicode_claim_hashes_stably(self):
        from provenance import canonicalize_claim, sha256_hex

        claim = "решение принято — DriftScore упал"
        assert sha256_hex(canonicalize_claim(claim)) == sha256_hex(claim)
        assert len(sha256_hex(claim)) == 64

    # --- C1 canonicalization ----------------------------------------------

    def test_canonicalization_vectors(self):
        from provenance import canonicalize_claim

        assert canonicalize_claim("a\r\nb  \n") == "a\nb"
        assert canonicalize_claim("  x  ") == "x"
        assert canonicalize_claim("a\rb") == "a\nb"

    # --- V2 precedence matrix ---------------------------------------------

    @pytest.mark.parametrize(
        "kw,expected",
        [
            ({}, "pass"),
            ({"current_hash": None}, "missing"),
            ({"current_hash": "h2"}, "mismatch"),
            ({"is_pruned": True}, "retracted"),
            ({"current_hash": "h2", "is_pruned": True}, "mismatch"),
            ({"current_hash": None, "is_pruned": True}, "missing"),
            ({"is_superseded": True, "synapses_loaded": True}, "retracted"),
            ({"is_superseded": True, "synapses_loaded": False}, "pass"),
        ],
    )
    def test_precedence_matrix(self, kw, expected):
        from provenance import classify_leaf_re_verification

        base = dict(
            leaf_id="L-1", recorded_hash="h1", current_hash="h1",
            is_pruned=False, is_superseded=False, synapses_loaded=False,
        )
        base.update(kw)
        assert classify_leaf_re_verification(**base) == expected

    # --- cross-field invariants (invisible to AST) -------------------------

    def test_r1_retractions_must_be_disjoint(self):
        from provenance import RetrievalProvenance

        with pytest.raises(ValueError):
            RetrievalProvenance(
                sink="s", answer_text="a", answer_text_hash="h",
                injected_leaf_ids=["L-1"], leaf_content_hashes={"L-1": "h1"},
                re_verification={"L-1": "pass"}, tree_root_at_trace="r",
                retractions_applied=["L-1"],
            )

    def test_r1_every_injected_leaf_needs_a_hash(self):
        from provenance import RetrievalProvenance

        with pytest.raises(ValueError):
            RetrievalProvenance(
                sink="s", answer_text="a", answer_text_hash="h",
                injected_leaf_ids=["L-1", "L-2"],
                leaf_content_hashes={"L-1": "h1"},
                re_verification={"L-1": "pass"}, tree_root_at_trace="r",
            )

    def test_hash_and_verification_keys_must_match(self):
        from provenance import RetrievalProvenance

        with pytest.raises(ValueError):
            RetrievalProvenance(
                sink="s", answer_text="a", answer_text_hash="h",
                injected_leaf_ids=["L-1"],
                leaf_content_hashes={"L-1": "h1"},
                re_verification={"L-1": "pass", "L-2": "pass"},
                tree_root_at_trace="r",
            )

    def test_r3_pass_with_method_none_is_illegal(self):
        from provenance import VerifierResult

        with pytest.raises(ValueError):
            VerifierResult(status="pass", method="none")

    def test_r2_empty_trace_derives_skipped_derived(self):
        from provenance import RetrievalProvenance, derive_verifier_result

        block = RetrievalProvenance(
            sink="s", answer_text="a", answer_text_hash="h",
            injected_leaf_ids=[], leaf_content_hashes={},
            re_verification={}, tree_root_at_trace="r",
        )
        result = derive_verifier_result(block)
        assert (result.status, result.method) == ("skipped", "derived")
        assert "empty trace (R2)" in result.notes

    def test_r3_aggregate_is_derived_not_asserted(self):
        from provenance import RetrievalProvenance, derive_verifier_result

        block = RetrievalProvenance(
            sink="s", answer_text="a", answer_text_hash="h",
            injected_leaf_ids=["L-1"], leaf_content_hashes={"L-1": "h1"},
            re_verification={"L-1": "mismatch"}, tree_root_at_trace="r",
        )
        result = derive_verifier_result(block)
        assert (result.status, result.method) == ("fail", "derived")

    # --- discriminator + R4/V1 --------------------------------------------

    def test_discriminator_rejects_both_blocks(self):
        from provenance import ProvenanceRecord, VerifierResult

        with pytest.raises(ValueError):
            ProvenanceRecord(
                record_id="x", record_kind="intake", timestamp="t", run_id="r",
                actor="whis", claim_content="c", claim_content_hash="h",
                retraction_expectation="normal",
                verifier_result=VerifierResult("skipped", "none"),
                intake=object(), retrieval=object(),
            )

    def test_r4_missing_required_field_raises_value_error(self):
        from provenance import ProvenanceRecord

        with pytest.raises(ValueError):
            ProvenanceRecord.from_dict({"record_kind": "retrieval"})

    def test_v1_unknown_field_does_not_raise_type_error(self):
        """v0.1's 'additive bumps the minor' promise was broken in practice:
        a record carrying a v0.2 field crashed a v0.1 reader."""
        from provenance import (
            ProvenanceRecord, RetrievalProvenance, VerifierResult, sha256_hex,
        )

        rec = ProvenanceRecord(
            record_id="x", record_kind="retrieval", timestamp="t", run_id="r",
            actor="cc", claim_content="c", claim_content_hash=sha256_hex("c"),
            retraction_expectation="normal",
            verifier_result=VerifierResult("skipped", "derived"),
            retrieval=RetrievalProvenance(
                sink="s", answer_text="a", answer_text_hash="h",
                injected_leaf_ids=[], leaf_content_hashes={},
                re_verification={}, tree_root_at_trace="r",
            ),
        )
        d = rec.to_dict()
        d["a_v03_field"] = "survives"
        assert ProvenanceRecord.from_dict(d).extras["a_v03_field"] == "survives"

    def test_c2_empty_claim_rejected(self):
        from provenance import (
            ProvenanceRecord, RetrievalProvenance, VerifierResult,
        )

        with pytest.raises(ValueError):
            ProvenanceRecord(
                record_id="x", record_kind="retrieval", timestamp="t",
                run_id="r", actor="cc", claim_content="   ",
                claim_content_hash="h", retraction_expectation="normal",
                verifier_result=VerifierResult("skipped", "derived"),
                retrieval=RetrievalProvenance(
                    sink="s", answer_text="a", answer_text_hash="h",
                    injected_leaf_ids=[], leaf_content_hashes={},
                    re_verification={}, tree_root_at_trace="r",
                ),
            )

    def test_source_type_pinning(self):
        from provenance import default_retraction_for

        assert default_retraction_for("roc-cold-read") == "high"
        assert default_retraction_for("handoff") == "normal"
        assert default_retraction_for(None) == "normal"

    def test_self_certification_invariant_fires(self):
        from provenance import assert_self_certification_blocked

        with pytest.raises(PermissionError):
            assert_self_certification_blocked("whis", "whis", "pass")
        assert assert_self_certification_blocked("cc", "whis", "pass") is None

    def test_canonical_json_matches_pcis_journal_convention(self):
        """PCIS hashes and sorts journal lines with these exact separators
        (core/events.py:73-77). The sibling's to_json uses defaults, so the
        two produce different bytes for the same record — PCIS pins its own
        here rather than inheriting the divergence."""
        from provenance import (
            ProvenanceRecord, RetrievalProvenance, VerifierResult, sha256_hex,
        )

        rec = ProvenanceRecord(
            record_id="x", record_kind="retrieval", timestamp="t", run_id="r",
            actor="cc", claim_content="c", claim_content_hash=sha256_hex("c"),
            retraction_expectation="normal",
            verifier_result=VerifierResult("skipped", "derived"),
            retrieval=RetrievalProvenance(
                sink="s", answer_text="a", answer_text_hash="h",
                injected_leaf_ids=[], leaf_content_hashes={},
                re_verification={}, tree_root_at_trace="r",
            ),
        )
        raw = rec.to_json()
        assert ", " not in raw and '": ' not in raw, (
            "canonical JSON must use separators=(',', ':')"
        )
        assert raw.index('"actor"') < raw.index('"claim_content"'), (
            "keys must be sorted"
        )
