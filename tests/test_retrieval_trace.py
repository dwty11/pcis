"""test_retrieval_trace.py — the verified retrieval trace.

THE LOAD-BEARING REQUIREMENT
============================
The trace must go RED when a logged leaf id does not re-verify against the
tree. Everything else here exists to stop that check from passing
vacuously.

THE CORE INVARIANT, AND WHY IT IS NOT THE OBVIOUS ONE
=====================================================
The recorded hash is a pure content hash of THE TEXT THAT WAS ACTUALLY
INJECTED — which comes from the search index (core/knowledge_search.py:288
reads data/search-index.json, never the tree). Re-verification compares it
against the tree's CURRENT content for that leaf id.

Two things this deliberately is NOT:

  * NOT the tree's content hashed at trace time. That is self-comparison —
    structurally guaranteed to pass, proving nothing. A stale index is the
    real signal: the model was shown text that is no longer in the record.

  * NOT ``hash_leaf(content, branch, created)``. That folds in the branch
    and the timestamp, which breaks the check in both directions:
    ``incremental_index`` (core/knowledge_search.py:268) stores INDEX time
    as ``created``, so every incrementally-added leaf would false-positive;
    and comparing injected content against the leaf's stored ``hash`` field
    reports pass when content was edited without that field being updated.

Both directions are asserted below (TestStaleIndex, TestNoFalsePositives)
so a future "simplification" to hash_leaf reds here.
"""

from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, _ROOT)

RUN = "trace-2026-07-25-001"
TS = "2026-07-25T15:30:00+03:00"


@pytest.fixture
def tree_env(tmp_path, monkeypatch):
    """A real tree with three leaves. Returns (kt, tree_path, ids)."""
    import knowledge_tree as kt

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(kt, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(kt, "TREE_FILE", str(data / "tree.json"))

    tree = {"branches": {}, "root_hash": ""}
    ids = {
        "stable": kt.add_knowledge(tree, "technical", "the root moves on every commit"),
        "drifts": kt.add_knowledge(tree, "technical", "DriftScore fell 3.1 points"),
        "goes": kt.add_knowledge(tree, "lessons", "this claim will be withdrawn"),
    }
    kt.save_tree(tree, str(data / "tree.json"))
    return kt, str(data / "tree.json"), ids


def _injection(kt, tree_path, ids, keys=None):
    """Build the (leaf_id, content_as_injected) list, in rank order, from
    the tree's current text — i.e. a FRESH index, the honest baseline."""
    tree = kt.load_tree(tree_path)
    by_id = {}
    for branch in tree["branches"].values():
        for leaf in branch["leaves"]:
            by_id[leaf["id"]] = leaf["content"]
    # `keys is not None`, not `keys or ids` — an explicitly empty list means
    # "cite nothing", which is the R2 empty-trace case.
    return [(ids[k], by_id[ids[k]]) for k in (ids if keys is None else keys)]


def _record(kt, tree_path, ids, keys=None, answer="an answer", **over):
    from retrieval_trace import build_retrieval_record

    kwargs = dict(
        sink="pcis.retrieval-trace",
        answer_text=answer,
        injection=_injection(kt, tree_path, ids, keys),
        tree=kt.load_tree(tree_path),
        run_id=RUN,
        timestamp=TS,
        actor="cc",
    )
    kwargs.update(over)
    return build_retrieval_record(**kwargs)


class TestHappyPath:
    def test_all_cited_leaves_resolve(self, tree_env):
        from retrieval_trace import verify_retrieval

        kt, path, ids = tree_env
        rec = _record(kt, path, ids)

        out = verify_retrieval(rec, tree=kt.load_tree(path))

        assert out["re_verification"] == {v: "pass" for v in ids.values()}
        assert out["root_state"] == "current"
        assert out["ok"] is True

    def test_record_is_a_retrieval_record_with_no_intake_block(self, tree_env):
        kt, path, ids = tree_env
        rec = _record(kt, path, ids)

        assert rec.record_kind == "retrieval"
        assert rec.intake is None
        assert rec.retrieval is not None

    def test_aggregate_is_derived_pass(self, tree_env):
        kt, path, ids = tree_env
        rec = _record(kt, path, ids)

        assert rec.verifier_result.status == "pass"
        assert rec.verifier_result.method == "derived"

    def test_injected_ids_are_stored_in_rank_order(self, tree_env):
        """Rank is observable and is NOT recoverable from answer_text_hash,
        so the field must preserve it even though record_id sorts."""
        kt, path, ids = tree_env
        order = ["goes", "stable", "drifts"]
        rec = _record(kt, path, ids, keys=order)

        assert rec.retrieval.injected_leaf_ids == [ids[k] for k in order]

    def test_record_id_is_order_independent(self, tree_env):
        kt, path, ids = tree_env
        a = _record(kt, path, ids, keys=["stable", "drifts", "goes"])
        b = _record(kt, path, ids, keys=["goes", "drifts", "stable"])

        assert a.record_id == b.record_id

    def test_record_id_changes_with_answer_text(self, tree_env):
        kt, path, ids = tree_env
        a = _record(kt, path, ids, answer="one answer")
        b = _record(kt, path, ids, answer="another answer")

        assert a.record_id != b.record_id


class TestMismatch:
    def test_coherent_rewrite_is_caught_when_nothing_else_can_see_it(self, tree_env):
        """The adversary case: content rewritten AND every tree hash healed,
        so verify_tree_integrity reports clean. The trace is the only
        discriminator."""
        from knowledge_synapses import find_leaf_in_tree
        from retrieval_trace import verify_retrieval

        kt, path, ids = tree_env
        rec = _record(kt, path, ids)

        tree = kt.load_tree(path)
        branch, leaf = find_leaf_in_tree(tree, ids["drifts"])
        leaf["content"] = "DriftScore fell 9.9 points"
        leaf["hash"] = kt.hash_leaf(leaf["content"], branch, leaf["created"])
        tree["branches"][branch]["hash"] = kt.compute_branch_hash(
            tree["branches"][branch]["leaves"]
        )
        tree["root_hash"] = kt.compute_root_hash(tree)
        assert kt.verify_tree_integrity(tree) == (True, []), (
            "the tamper must be internally consistent, or a tree-level check "
            "would catch it and this test would not isolate the trace"
        )

        out = verify_retrieval(rec, tree=tree)

        assert out["re_verification"][ids["drifts"]] == "mismatch"
        assert out["re_verification"][ids["stable"]] == "pass"
        assert out["ok"] is False

    def test_content_edited_without_updating_stored_hash(self, tree_env):
        """Forces comparison against the tree's CONTENT, not its stored hash
        field. A stored-hash comparison reports pass here, because the stale
        hash still equals the recorded one."""
        from knowledge_synapses import find_leaf_in_tree
        from retrieval_trace import verify_retrieval

        kt, path, ids = tree_env
        rec = _record(kt, path, ids)

        tree = kt.load_tree(path)
        _branch, leaf = find_leaf_in_tree(tree, ids["drifts"])
        leaf["content"] = "tampered content"  # touch nothing else
        ok, errors = kt.verify_tree_integrity(tree)
        assert ok is False and any("content-hash mismatch" in e for e in errors)

        out = verify_retrieval(rec, tree=tree)

        assert out["re_verification"][ids["drifts"]] == "mismatch"


class TestMissing:
    def test_hard_pruned_leaf_is_missing(self, tree_env):
        from retrieval_trace import verify_retrieval

        kt, path, ids = tree_env
        rec = _record(kt, path, ids)

        tree = kt.load_tree(path)
        assert kt.prune_leaf(tree, "lessons", ids["goes"], hard=True) is True
        tree["root_hash"] = kt.compute_root_hash(tree)

        out = verify_retrieval(rec, tree=tree)

        assert out["re_verification"][ids["goes"]] == "missing"
        assert out["re_verification"][ids["stable"]] == "pass"
        assert out["ok"] is False

    def test_every_logged_id_appears_in_the_result(self, tree_env):
        """A dropped leaf must not silently shrink the map."""
        from retrieval_trace import verify_retrieval

        kt, path, ids = tree_env
        rec = _record(kt, path, ids)
        tree = kt.load_tree(path)
        kt.prune_leaf(tree, "lessons", ids["goes"], hard=True)
        tree["root_hash"] = kt.compute_root_hash(tree)

        out = verify_retrieval(rec, tree=tree)

        assert set(out["re_verification"]) == set(rec.retrieval.injected_leaf_ids)

    def test_missing_is_keyed_on_leaf_id_not_content_hash(self, tree_env, monkeypatch):
        """Two leaves with identical content share a content hash. Resolving
        by hash would report pass for a deleted leaf because its twin
        survives — a silent-deletion hole."""
        from retrieval_trace import verify_retrieval

        kt, path, ids = tree_env
        monkeypatch.setattr(kt, "now_utc", lambda: "2026-07-25 12:00:00 UTC")
        tree = kt.load_tree(path)
        a = kt.add_knowledge(tree, "lessons", "duplicate content")
        b = kt.add_knowledge(tree, "lessons", "duplicate content")
        kt.save_tree(tree, path)
        assert a != b

        rec = _record(kt, path, {"a": a}, keys=["a"])

        tree = kt.load_tree(path)
        assert kt.prune_leaf(tree, "lessons", a, hard=True) is True
        tree["root_hash"] = kt.compute_root_hash(tree)
        # b survives with byte-identical content.
        out = verify_retrieval(rec, tree=tree)

        assert out["re_verification"][a] == "missing"


class TestRetracted:
    def test_soft_pruned_leaf_is_retracted(self, tree_env):
        """Soft prune leaves the hash and root untouched by design, so
        without this the withdrawn claim re-verifies clean."""
        from retrieval_trace import verify_retrieval

        kt, path, ids = tree_env
        rec = _record(kt, path, ids)

        tree = kt.load_tree(path)
        assert kt.prune_leaf(tree, "lessons", ids["goes"], hard=False) is True

        out = verify_retrieval(rec, tree=tree)

        assert out["re_verification"][ids["goes"]] == "retracted"
        assert out["ok"] is False

    def test_pruned_and_drifted_reads_mismatch(self, tree_env):
        """Precedence: integrity outranks lifecycle."""
        from knowledge_synapses import find_leaf_in_tree
        from retrieval_trace import verify_retrieval

        kt, path, ids = tree_env
        rec = _record(kt, path, ids)

        tree = kt.load_tree(path)
        kt.prune_leaf(tree, "lessons", ids["goes"], hard=False)
        _branch, leaf = find_leaf_in_tree(tree, ids["goes"])
        leaf["content"] = "withdrawn AND rewritten"

        out = verify_retrieval(rec, tree=tree)

        assert out["re_verification"][ids["goes"]] == "mismatch"

    def test_superseded_reads_pass_when_synapses_absent(self, tree_env):
        """The caveat, asserted so it cannot be mistaken for coverage:
        supersession is best-effort. With no synapse graph loaded, a
        superseded leaf reads pass — absence of evidence, not evidence of
        absence."""
        from retrieval_trace import verify_retrieval

        kt, path, ids = tree_env
        rec = _record(kt, path, ids)

        out = verify_retrieval(rec, tree=kt.load_tree(path), synapses=None)

        assert out["synapses_loaded"] is False
        assert out["re_verification"][ids["goes"]] == "pass"

    def test_superseded_is_retracted_when_synapses_loaded(self, tree_env):
        from retrieval_trace import verify_retrieval

        kt, path, ids = tree_env
        rec = _record(kt, path, ids)
        synapses = {
            "synapses": [
                {
                    "from_leaf": ids["stable"],
                    "to_leaf": ids["goes"],
                    "relation": "SUPERSEDES",
                }
            ]
        }

        out = verify_retrieval(rec, tree=kt.load_tree(path), synapses=synapses)

        assert out["synapses_loaded"] is True
        assert out["re_verification"][ids["goes"]] == "retracted"


class TestRootAnchor:
    def test_stale_root_flagged_though_every_leaf_passes(self, tree_env):
        from retrieval_trace import verify_retrieval

        kt, path, ids = tree_env
        rec = _record(kt, path, ids)

        tree = kt.load_tree(path)
        kt.add_knowledge(tree, "philosophy", "an unrelated leaf")
        tree["branches"]["philosophy"]["hash"] = kt.compute_branch_hash(
            tree["branches"]["philosophy"]["leaves"]
        )
        tree["root_hash"] = kt.compute_root_hash(tree)

        out = verify_retrieval(rec, tree=tree)

        assert all(s == "pass" for s in out["re_verification"].values())
        assert out["root_state"] == "stale"
        assert out["root_recorded"] != out["root_current"]
        assert out["ok"] is False

    def test_unmutated_tree_reports_current(self, tree_env):
        """Negative control — without this, an always-stale implementation
        would green the test above."""
        from retrieval_trace import verify_retrieval

        kt, path, ids = tree_env
        rec = _record(kt, path, ids)

        out = verify_retrieval(rec, tree=kt.load_tree(path))

        assert out["root_state"] == "current"
        assert out["root_recorded"] == out["root_current"]

    def test_anchors_on_root_hash_not_combined_root_hash(self, tree_env):
        kt, path, ids = tree_env
        rec = _record(kt, path, ids)
        tree = kt.load_tree(path)

        assert rec.retrieval.tree_root_at_trace == kt.compute_root_hash(tree)
        assert rec.retrieval.tree_root_at_trace != tree.get("combined_root_hash")

    def test_root_is_full_length(self, tree_env):
        kt, path, ids = tree_env
        rec = _record(kt, path, ids)

        assert len(rec.retrieval.tree_root_at_trace) == 64
        int(rec.retrieval.tree_root_at_trace, 16)

    def test_stale_root_survives_the_real_write_path(self, tree_env):
        from retrieval_trace import verify_retrieval

        kt, path, ids = tree_env
        rec = _record(kt, path, ids)

        with kt.tree_lock(path=path) as t:
            kt.add_knowledge(t, "philosophy", "written through tree_lock")

        out = verify_retrieval(rec, tree=kt.load_tree(path))

        assert out["root_state"] == "stale"
        assert all(s == "pass" for s in out["re_verification"].values())


class TestStaleIndex:
    """The core invariant, forward direction: the model was shown text that
    is no longer what the tree holds."""

    def test_stale_index_copy_is_caught_at_trace_time(self, tree_env):
        from retrieval_trace import build_retrieval_record, verify_retrieval

        kt, path, ids = tree_env
        # The index still holds pre-edit text; the tree has moved on.
        stale_injection = [(ids["drifts"], "DriftScore fell 3.1 points")]

        tree = kt.load_tree(path)
        from knowledge_synapses import find_leaf_in_tree

        _b, leaf = find_leaf_in_tree(tree, ids["drifts"])
        leaf["content"] = "DriftScore fell 9.9 points"
        kt.save_tree(tree, path)

        rec = build_retrieval_record(
            sink="pcis.retrieval-trace",
            answer_text="the score fell 3.1 points",
            injection=stale_injection,
            tree=kt.load_tree(path),
            run_id=RUN,
            timestamp=TS,
        )

        assert rec.retrieval.re_verification[ids["drifts"]] == "mismatch"
        assert rec.verifier_result.status == "fail"

        out = verify_retrieval(rec, tree=kt.load_tree(path))
        assert out["re_verification"][ids["drifts"]] == "mismatch"

    def test_recorded_hash_is_of_the_injected_text_not_the_tree(self, tree_env):
        from retrieval_trace import build_retrieval_record, content_hash

        kt, path, ids = tree_env
        injected = "a truncated or stale copy"

        rec = build_retrieval_record(
            sink="s", answer_text="a", injection=[(ids["stable"], injected)],
            tree=kt.load_tree(path), run_id=RUN, timestamp=TS,
        )

        assert rec.retrieval.leaf_content_hashes[ids["stable"]] == content_hash(injected)


class TestNoFalsePositives:
    """The core invariant, reverse direction: legitimate adds must not be
    flagged."""

    def test_incremental_index_created_skew_does_not_flag(self, tree_env):
        """incremental_index stores INDEX time as `created`, not the leaf's.
        Any implementation that recomputed hash_leaf(content, branch,
        created) from an index entry would report mismatch for every
        incrementally-added leaf. A pure content hash cannot."""
        from retrieval_trace import verify_retrieval

        kt, path, ids = tree_env
        tree = kt.load_tree(path)
        lid = kt.add_knowledge(tree, "technical", "added via pcis add")
        kt.save_tree(tree, path)

        # The index entry that `pcis add` would have written: right content,
        # WRONG created timestamp.
        rec = _record(kt, path, {"added": lid}, keys=["added"])

        out = verify_retrieval(rec, tree=kt.load_tree(path))

        assert out["re_verification"][lid] == "pass"

    def test_confidence_change_does_not_flag_content(self, tree_env):
        """Confidence is outside the content hash — a decay pass must not
        read as content drift."""
        from knowledge_synapses import find_leaf_in_tree
        from retrieval_trace import verify_retrieval

        kt, path, ids = tree_env
        rec = _record(kt, path, ids)

        tree = kt.load_tree(path)
        _b, leaf = find_leaf_in_tree(tree, ids["stable"])
        leaf["confidence"] = 0.11

        out = verify_retrieval(rec, tree=tree)

        assert out["re_verification"][ids["stable"]] == "pass"


class TestR1RetractionsDisjoint:
    def test_filtered_leaf_is_not_in_injected(self, tree_env):
        kt, path, ids = tree_env
        rec = _record(
            kt, path, ids, keys=["stable", "drifts"],
            retractions_applied=[ids["goes"]],
        )

        assert ids["goes"] not in rec.retrieval.injected_leaf_ids
        assert rec.retrieval.retractions_applied == [ids["goes"]]

    def test_empty_trace_is_skipped_not_pass(self, tree_env):
        kt, path, ids = tree_env
        rec = _record(kt, path, ids, keys=[])

        assert rec.verifier_result.status == "skipped"
        assert rec.retrieval.injected_leaf_ids == []


class TestN2SameAnswerDifferentOrder:
    """N2 — can the SAME answer_text arise from the same leaf set in
    observably DIFFERENT orders? Answered against the real search().

    Yes. ``search`` sorts by score alone (core/knowledge_search.py:309), so
    an exact tie falls through to Python's STABLE sort, which preserves the
    iteration order of ``index["embeddings"]`` — dict insertion order in
    search-index.json. That order differs between a full ``reindex()``
    (walks tree order, :211) and ``incremental_index`` (appends on
    ``pcis add``, :263). Exact ties are reachable whenever two leaves share
    content, and duplicate content is unprevented.

    Two consequences, both asserted here:

      * ``sorted()`` in the record_id preimage is CORRECT and load-bearing.
        Without it, a benign reindex that merely permuted tied leaves would
        mint a new record_id for a byte-identical answer.
      * Rank is therefore NOT recoverable from ``answer_text_hash`` — the
        spec's stated rationale for sorting is unsound in exactly this case,
        even though the conclusion holds. So ``injected_leaf_ids`` must
        preserve rank order, which is what makes rank observable at all.
    """

    @pytest.fixture
    def tied_index(self, tmp_path, monkeypatch):
        """A real index with two distinct ids holding identical content, so
        their cosine scores tie exactly. Returns (build, ids).

        Uses the package-qualified ``core.knowledge_search`` rather than the
        bare ``knowledge_search``. Both resolve today, but the bare alias is
        the one a sys.modules mock can hijack: test_telegram_notify.py used
        to park a MagicMock under that key at module scope without restoring
        it, which silently poisoned every test imported afterwards. That is
        fixed, and the package-qualified form is the alias that never had
        the exposure.
        """
        import core.knowledge_search as ks

        vector = [0.5, 0.25, 0.125, 0.0625]
        monkeypatch.setattr(ks, "get_embedding", lambda t, model=None: list(vector))
        dup = "the root moves on every commit"
        a, b = "leaf-aaa", "leaf-bbb"

        def build(order):
            import json

            index = {
                "model": "m", "dimensions": 4, "created": "c",
                "last_reindex": "c", "leaf_count": 2, "embeddings": {},
            }
            for lid in order:
                index["embeddings"][lid] = {
                    "branch": "technical", "content": dup, "source": "s",
                    "confidence": 0.8, "created": "2026-01-01 00:00:00 UTC",
                    "vector": list(vector),
                }
            p = tmp_path / f"idx-{'-'.join(order)}.json"
            p.write_text(json.dumps(index), encoding="utf-8")
            monkeypatch.setattr(ks, "INDEX_FILE", str(p))
            return ks.search("anything", top_k=5)

        return build, (a, b)

    def test_tied_leaves_come_back_in_index_insertion_order(self, tied_index):
        build, (a, b) = tied_index

        forward = build([a, b])
        reverse = build([b, a])

        assert [lid for _s, lid, _d in forward] == [a, b]
        assert [lid for _s, lid, _d in reverse] == [b, a]
        # Same set, same scores — only the order differs.
        assert {lid for _s, lid, _d in forward} == {lid for _s, lid, _d in reverse}
        assert [s for s, _l, _d in forward] == [s for s, _l, _d in reverse]

    def test_identical_content_yields_byte_identical_answer_either_way(
        self, tied_index
    ):
        """So rank is NOT folded into answer_text_hash."""
        from retrieval_trace import injection_from_search

        build, (a, b) = tied_index
        forward = injection_from_search(build([a, b]))
        reverse = injection_from_search(build([b, a]))

        answer_f = "\n".join(c for _lid, c in forward)
        answer_r = "\n".join(c for _lid, c in reverse)
        assert answer_f == answer_r
        assert [lid for lid, _c in forward] != [lid for lid, _c in reverse]

    def test_record_id_is_stable_across_the_permutation(self, tied_index, tree_env):
        """The payoff: a benign reindex does not mint a new record."""
        from retrieval_trace import build_retrieval_record, injection_from_search

        kt, path, _ids = tree_env
        build, (a, b) = tied_index
        tree = kt.load_tree(path)
        answer = "the root moves on every commit"

        def rec_for(order):
            return build_retrieval_record(
                sink="s", answer_text=answer,
                injection=injection_from_search(build(order)),
                tree=tree, run_id=RUN, timestamp=TS,
            )

        forward, reverse = rec_for([a, b]), rec_for([b, a])

        assert forward.record_id == reverse.record_id
        # ...while rank stays observable in the field itself.
        assert forward.retrieval.injected_leaf_ids != \
            reverse.retrieval.injected_leaf_ids


class TestSummarize:
    """The reader-facing line. It must never claim 'unchanged' while
    reporting drift, and never render an empty trace as all-pass."""

    def test_all_pass_says_unchanged(self, tree_env):
        from retrieval_trace import summarize, verify_retrieval

        kt, path, ids = tree_env
        rec = _record(kt, path, ids)

        line = summarize(verify_retrieval(rec, tree=kt.load_tree(path)))

        assert line.startswith("retrieval trace: 3/3 cited leaves resolve")
        assert "unchanged since trace" in line

    def test_drift_is_named_and_never_called_unchanged(self, tree_env):
        from knowledge_synapses import find_leaf_in_tree
        from retrieval_trace import summarize, verify_retrieval

        kt, path, ids = tree_env
        rec = _record(kt, path, ids)
        tree = kt.load_tree(path)
        _b, leaf = find_leaf_in_tree(tree, ids["drifts"])
        leaf["content"] = "rewritten"

        line = summarize(verify_retrieval(rec, tree=tree))

        assert "2/3 cited leaves resolve" in line
        assert "1 drifted" in line
        assert "unchanged" not in line, (
            "must not claim 'unchanged' while reporting drift"
        )

    def test_mixed_statuses_are_all_named(self, tree_env):
        from knowledge_synapses import find_leaf_in_tree
        from retrieval_trace import summarize, verify_retrieval

        kt, path, ids = tree_env
        rec = _record(kt, path, ids)
        tree = kt.load_tree(path)
        _b, leaf = find_leaf_in_tree(tree, ids["drifts"])
        leaf["content"] = "rewritten"
        kt.prune_leaf(tree, "lessons", ids["goes"], hard=True)
        tree["root_hash"] = kt.compute_root_hash(tree)

        line = summarize(verify_retrieval(rec, tree=tree))

        assert "1/3 cited leaves resolve" in line
        assert "1 drifted" in line
        assert "1 gone" in line
        assert "unchanged" not in line

    def test_empty_trace_reads_as_no_cited_leaves(self, tree_env):
        from retrieval_trace import summarize, verify_retrieval

        kt, path, ids = tree_env
        rec = _record(kt, path, ids, keys=[])

        assert summarize(verify_retrieval(rec, tree=kt.load_tree(path))) == \
            "retrieval trace: no cited leaves"


class TestSabotageProbe:
    """Anti-vacuity. If the module re-implements the tree primitives
    internally instead of importing them, these patches go inert and the
    sabotaged run still reports clean."""

    def test_patching_root_computation_flips_to_stale(self, tree_env, monkeypatch):
        import retrieval_trace as rt
        from retrieval_trace import verify_retrieval

        kt, path, ids = tree_env
        rec = _record(kt, path, ids)

        monkeypatch.setattr(rt, "compute_root_hash", lambda t: "f" * 64)
        out = verify_retrieval(rec, tree=kt.load_tree(path))

        assert out["root_state"] == "stale"

    def test_patching_content_hash_flips_every_leaf(self, tree_env, monkeypatch):
        import retrieval_trace as rt
        from retrieval_trace import verify_retrieval

        kt, path, ids = tree_env
        rec = _record(kt, path, ids)

        monkeypatch.setattr(rt, "content_hash", lambda c: "0" * 64)
        out = verify_retrieval(rec, tree=kt.load_tree(path))

        assert set(out["re_verification"].values()) == {"mismatch"}

    def test_results_are_not_cached_between_calls(self, tree_env):
        from retrieval_trace import verify_retrieval

        kt, path, ids = tree_env
        rec = _record(kt, path, ids)
        assert verify_retrieval(rec, tree=kt.load_tree(path))["ok"] is True

        tree = kt.load_tree(path)
        kt.prune_leaf(tree, "lessons", ids["goes"], hard=True)
        tree["root_hash"] = kt.compute_root_hash(tree)

        assert verify_retrieval(rec, tree=tree)["ok"] is False
