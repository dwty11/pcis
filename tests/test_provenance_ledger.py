"""test_provenance_ledger.py — the plain append-only provenance ledger.

SCOPE, DELIBERATELY NARROW
==========================
This is an append-only JSONL file and nothing more. There is NO hash chain,
by decision: the chain is a v0.3 design task with three unresolved
questions (field convention vs the shared spec, concurrent-append chain
forking, and no branch-to-tree-root proof path). Shipping a plain ledger
now avoids pre-empting any of them.

``test_ledger_lines_carry_no_chain_fields`` asserts the absence, so nobody
reads this file as a tamper-evident log or bolts a half-chain onto it by
accident.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, _ROOT)


def _make_record(answer="an answer", leaf="L-1"):
    from provenance import (
        ProvenanceRecord, RetrievalProvenance, VerifierResult, sha256_hex,
        retrieval_idempotency_key,
    )

    block = RetrievalProvenance(
        sink="pcis.retrieval-trace",
        answer_text=answer,
        answer_text_hash=sha256_hex(answer),
        injected_leaf_ids=[leaf],
        leaf_content_hashes={leaf: "h1"},
        re_verification={leaf: "pass"},
        tree_root_at_trace="a" * 64,
    )
    return ProvenanceRecord(
        record_id=retrieval_idempotency_key(answer, [leaf], "a" * 64),
        record_kind="retrieval",
        timestamp="2026-07-25T15:30:00+03:00",
        run_id="trace-001",
        actor="cc",
        claim_content=answer,
        claim_content_hash=sha256_hex(answer),
        retraction_expectation="normal",
        verifier_result=VerifierResult("skipped", "derived"),
        retrieval=block,
    )


@pytest.fixture
def base(tmp_path, monkeypatch):
    """PCIS_BASE_DIR pointed at a tmp dir. Deliberately does NOT create
    data/ — the module's own makedirs must be what creates it."""
    monkeypatch.setenv("PCIS_BASE_DIR", str(tmp_path))
    return tmp_path


class TestDefaultPath:
    def test_writes_to_data_provenance_ledger_jsonl(self, base):
        from provenance_ledger import append_record

        append_record(_make_record())

        expected = base / "data" / "provenance-ledger.jsonl"
        assert expected.exists(), f"ledger should land at {expected}"

    def test_creates_the_data_directory(self, base):
        from provenance_ledger import append_record

        assert not (base / "data").exists()
        append_record(_make_record())
        assert (base / "data").is_dir()

    def test_base_dir_is_resolved_per_call_not_at_import(self, base, tmp_path,
                                                         monkeypatch):
        """An import-time BASE_DIR would make every fixture-based test write
        into the developer's real repo data/."""
        from provenance_ledger import append_record

        other = tmp_path / "elsewhere"
        monkeypatch.setenv("PCIS_BASE_DIR", str(other))
        append_record(_make_record())

        assert (other / "data" / "provenance-ledger.jsonl").exists()
        assert not (base / "data" / "provenance-ledger.jsonl").exists()

    def test_explicit_path_wins(self, base, tmp_path):
        from provenance_ledger import append_record

        target = tmp_path / "custom" / "led.jsonl"
        append_record(_make_record(), ledger_path=str(target))

        assert target.exists()
        assert not (base / "data" / "provenance-ledger.jsonl").exists()


class TestAppendAndRead:
    def test_one_line_per_record(self, base):
        from provenance_ledger import append_record, ledger_path

        for i in range(3):
            append_record(_make_record(answer=f"answer {i}"))

        lines = open(ledger_path(), encoding="utf-8").read().splitlines()
        assert len(lines) == 3

    def test_lines_are_newline_terminated(self, base):
        from provenance_ledger import append_record, ledger_path

        append_record(_make_record())
        assert open(ledger_path(), encoding="utf-8").read().endswith("\n")

    def test_records_round_trip(self, base):
        from provenance_ledger import append_record, load_ledger

        rec = _make_record()
        append_record(rec)

        loaded = load_ledger()
        assert len(loaded) == 1
        assert loaded[0].record_id == rec.record_id
        assert loaded[0].to_json() == rec.to_json()

    def test_order_is_preserved(self, base):
        from provenance_ledger import append_record, load_ledger

        for i in range(4):
            append_record(_make_record(answer=f"answer {i}"))

        assert [r.retrieval.answer_text for r in load_ledger()] == [
            f"answer {i}" for i in range(4)
        ]

    def test_lines_are_canonical_json(self, base):
        """Same convention as core/events.py:73-77 — sorted keys, no spaces."""
        from provenance_ledger import append_record, ledger_path

        append_record(_make_record())
        raw = open(ledger_path(), encoding="utf-8").read().strip()

        assert ", " not in raw and '": ' not in raw
        parsed = json.loads(raw)
        assert list(parsed) == sorted(parsed)

    def test_non_ascii_survives_unescaped(self, base):
        from provenance_ledger import append_record, load_ledger, ledger_path

        rec = _make_record(answer="решение принято — DriftScore упал")
        append_record(rec)

        assert "решение" in open(ledger_path(), encoding="utf-8").read()
        assert load_ledger()[0].retrieval.answer_text == rec.retrieval.answer_text

    def test_missing_ledger_reads_as_empty(self, base):
        from provenance_ledger import load_ledger

        assert load_ledger() == []

    def test_blank_lines_are_ignored(self, base):
        from provenance_ledger import append_record, ledger_path, load_ledger

        append_record(_make_record())
        with open(ledger_path(), "a", encoding="utf-8") as f:
            f.write("\n   \n")

        assert len(load_ledger()) == 1

    def test_malformed_line_raises_rather_than_being_skipped(self, base):
        """R4 propagates: a bad line is a finding, not something to drop."""
        from provenance_ledger import append_record, ledger_path, load_ledger

        append_record(_make_record())
        with open(ledger_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps({"record_kind": "retrieval"}) + "\n")

        with pytest.raises(ValueError):
            load_ledger()

    def test_malformed_line_names_its_line_number(self, base):
        from provenance_ledger import append_record, ledger_path, load_ledger

        append_record(_make_record())
        with open(ledger_path(), "a", encoding="utf-8") as f:
            f.write("{not json\n")

        with pytest.raises(ValueError, match="line 2"):
            load_ledger()


class TestNoChain:
    def test_ledger_lines_carry_no_chain_fields(self, base):
        """Asserted absence. The chain is deferred to v0.3; a half-present
        chain field would imply tamper-evidence this file does not provide."""
        from provenance_ledger import append_record, ledger_path

        append_record(_make_record())
        parsed = json.loads(open(ledger_path(), encoding="utf-8").read())

        for forbidden in (
            "prev_hash", "prev_event_hash", "event_hash", "record_hash", "chain",
        ):
            assert forbidden not in parsed, (
                f"{forbidden!r} present — this ledger is deliberately NOT "
                f"chained (v0.3). Do not add half a chain."
            )

    def test_module_exposes_no_verify_chain(self):
        """No API that would let a caller believe the chain exists."""
        import provenance_ledger

        for absent in ("verify_chain", "verify_ledger_chain"):
            assert not hasattr(provenance_ledger, absent)


class TestDedupe:
    def test_appends_duplicates_by_default(self, base):
        """Append-only means append. record_id is an idempotency key, but
        whether a repeat write collapses is the CALLER's decision — the
        shared spec does not rule on it, so this does not choose silently."""
        from provenance_ledger import append_record, load_ledger

        rec = _make_record()
        assert append_record(rec) is True
        assert append_record(rec) is True

        assert len(load_ledger()) == 2

    def test_dedupe_true_skips_an_existing_record_id(self, base):
        from provenance_ledger import append_record, load_ledger

        rec = _make_record()
        assert append_record(rec, dedupe=True) is True
        assert append_record(rec, dedupe=True) is False

        assert len(load_ledger()) == 1

    def test_dedupe_does_not_block_a_different_record(self, base):
        from provenance_ledger import append_record, load_ledger

        append_record(_make_record(answer="one"), dedupe=True)
        append_record(_make_record(answer="two"), dedupe=True)

        assert len(load_ledger()) == 2

    def test_has_record(self, base):
        from provenance_ledger import append_record, has_record

        rec = _make_record()
        assert has_record(rec.record_id) is False
        append_record(rec)
        assert has_record(rec.record_id) is True

    def test_find_by_record_id(self, base):
        from provenance_ledger import append_record, find_by_record_id

        rec = _make_record()
        append_record(_make_record(answer="unrelated"))
        append_record(rec)

        found = find_by_record_id(rec.record_id)
        assert found is not None
        assert found.record_id == rec.record_id
        assert find_by_record_id("0" * 16) is None


class TestLogRetrievalEndToEnd:
    """The composed path: build a trace from a real tree and persist it."""

    @pytest.fixture
    def tree(self, base, monkeypatch):
        import knowledge_tree as kt

        data = base / "data"
        data.mkdir(exist_ok=True)
        monkeypatch.setattr(kt, "BASE_DIR", str(base))
        monkeypatch.setattr(kt, "TREE_FILE", str(data / "tree.json"))
        t = {"branches": {}, "root_hash": ""}
        leaf_id = kt.add_knowledge(t, "technical", "the root moves on every commit")
        kt.save_tree(t, str(data / "tree.json"))
        return kt, str(data / "tree.json"), leaf_id

    def test_log_retrieval_persists_a_verifiable_record(self, base, tree):
        from provenance_ledger import load_ledger
        from retrieval_trace import log_retrieval, verify_retrieval

        kt, path, leaf_id = tree
        loaded = kt.load_tree(path)

        rec = log_retrieval(
            answer_text="the root moves on every commit",
            injection=[(leaf_id, "the root moves on every commit")],
            tree=loaded,
            run_id="trace-001",
            timestamp="2026-07-25T15:30:00+03:00",
        )

        persisted = load_ledger()
        assert len(persisted) == 1
        assert persisted[0].record_id == rec.record_id

        out = verify_retrieval(persisted[0], tree=kt.load_tree(path))
        assert out["re_verification"][leaf_id] == "pass"
        assert out["ok"] is True

    def test_log_retrieval_reverifies_from_the_ledger_after_a_tamper(
        self, base, tree
    ):
        """The whole point: a trace read back off disk still catches drift."""
        from knowledge_synapses import find_leaf_in_tree
        from provenance_ledger import load_ledger
        from retrieval_trace import log_retrieval, verify_retrieval

        kt, path, leaf_id = tree
        log_retrieval(
            answer_text="an answer",
            injection=[(leaf_id, "the root moves on every commit")],
            tree=kt.load_tree(path),
            run_id="trace-001",
            timestamp="2026-07-25T15:30:00+03:00",
        )

        t = kt.load_tree(path)
        _b, leaf = find_leaf_in_tree(t, leaf_id)
        leaf["content"] = "rewritten after the trace"
        kt.save_tree(t, path)

        out = verify_retrieval(load_ledger()[0], tree=kt.load_tree(path))

        assert out["re_verification"][leaf_id] == "mismatch"
        assert out["ok"] is False
