"""test_provenance_api.py — the reader surface for retrieval traces.

Gap 3 from the observability review: the ledger had no reader at all
(``grep -c provenance demo/index.html`` → 0, no route), so a feature that
worked was invisible to anyone with a browser.

WHAT THESE TESTS PROTECT
========================
The API shape is where the honesty constraints are enforced, because a UI
can only render what it is given. Two structural choices are load-bearing
and are pinned here:

1. **No bare pass/fail field is exposed.** ``verify_retrieval`` returns
   ``ok``, documented as "not a statement about the answer". Serving it
   would invite exactly the green "Verified" chip the module bans, so the
   detail route serves the honest summary line and per-leaf statuses
   instead. A caller cannot render a bare chip from this payload without
   inventing one.

2. **Display vocabulary only.** ``resolves / drifted / gone / withdrawn``
   reach the client; the wire values ``pass / mismatch / missing /
   retracted`` never do.

Plus ``synapses_loaded``, which must always be present: a superseded leaf
reads ``pass`` when no synapse graph was loaded, and absence of evidence
rendered as evidence of absence is the failure mode that flag exists for.
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
sys.path.insert(0, _HERE)

# Reuse the emitter suite's real tree + index fixture rather than rebuilding
# a second, subtly different one.
from test_retrieval_trace_wiring import (  # noqa: E402,F401
    _break_ledger,
    _break_semantic_search,
    _ledger,
    env,
)

WIRE_VALUES = {"pass", "mismatch", "missing", "retracted"}
DISPLAY_VALUES = {"resolves", "drifted", "gone", "withdrawn"}


@pytest.fixture
def route(env, monkeypatch, tmp_path):
    from demo import server

    kt, paths, ids = env
    monkeypatch.setattr(server, "DEMO_TREE_FILE", paths["tree"])
    monkeypatch.setattr(server, "DEMO_DIR", str(tmp_path / "demo_out"))
    os.makedirs(str(tmp_path / "demo_out"), exist_ok=True)
    return server.app.test_client(), paths, ids


def _run_query(client, q="deploys"):
    """Run a retrieval so there is something to read back."""
    resp = client.post("/api/query", json={"query": q})
    assert resp.status_code == 200
    return resp.get_json()


class TestQueryResponseCarriesRecordId:
    def test_query_returns_the_record_id_it_just_wrote(self, route):
        client, paths, ids = route

        payload = _run_query(client)

        assert payload["provenance_record_id"], (
            "the browser cannot fetch a trace it was never told the id of"
        )
        assert payload["provenance_record_id"] == _ledger(paths["base"])[0].record_id

    def test_record_id_is_null_when_nothing_was_recorded(self, route, monkeypatch):
        """A failed ledger write must read as 'not recorded', not as absence.

        Silence here is what let a broken emitter look identical to a
        working one for as long as it did.
        """
        client, paths, ids = route
        _break_ledger(monkeypatch)

        payload = _run_query(client)

        assert payload["results"], "results still served"
        assert payload["provenance_record_id"] is None


class TestProvenanceList:
    def test_lists_records_newest_first(self, route):
        client, paths, ids = route
        _run_query(client, "deploys")
        _run_query(client, "root")

        listing = client.get("/api/provenance").get_json()

        assert listing["total"] == 2
        stamps = [r["timestamp"] for r in listing["records"]]
        assert stamps == sorted(stamps, reverse=True), "newest first"

    def test_each_row_says_how_the_leaves_were_selected(self, route):
        client, paths, ids = route
        _run_query(client)

        row = client.get("/api/provenance").get_json()["records"][0]

        assert row["retrieval_mode"] in {"semantic", "keyword"}
        assert row["sink"] == "pcis.retrieval-trace/demo.query"
        assert row["leaves"] >= 1

    def test_empty_ledger_is_not_an_error(self, route):
        client, paths, ids = route

        listing = client.get("/api/provenance")

        assert listing.status_code == 200
        assert listing.get_json()["records"] == []


def _tamper_a_leaf(tree_path, marker="[[TAMPERED BY COLD READ]] "):
    """Edit a leaf's CONTENT and leave its stored hash alone — the naive tamper.

    Tree integrity catches this (content no longer hashes to the stored value).
    The retrieval trace cannot, on a tree-sourced path: the tampered text is
    what got injected, so it is what the record attests to.
    """
    import knowledge_tree as kt

    tree = kt.load_tree(tree_path)
    for bname, branch in tree["branches"].items():
        for leaf in branch["leaves"]:
            leaf_id = leaf["id"]
            leaf["content"] = marker + leaf["content"]
            with open(tree_path, "w", encoding="utf-8") as f:
                json.dump(tree, f)
            return leaf_id
    raise AssertionError("fixture had no leaf to tamper")


class TestAttestabilityReachesTheClient:
    def test_keyword_fallback_is_labelled_tree_sourced(self, route, monkeypatch):
        client, paths, ids = route
        _break_semantic_search(monkeypatch)

        rec_id = _run_query(client, "root")["provenance_record_id"]
        detail = client.get(f"/api/provenance/{rec_id}").get_json()

        assert detail["injection_source"] == "tree"
        assert detail["attestable"] is False

    def test_semantic_path_is_labelled_index_sourced_and_attestable(self, route):
        client, paths, ids = route

        rec_id = _run_query(client)["provenance_record_id"]
        detail = client.get(f"/api/provenance/{rec_id}").get_json()

        assert detail["injection_source"] == "index"
        assert detail["attestable"] is True

    def test_unattestable_detail_sends_NO_per_leaf_verdict(self, route, monkeypatch):
        """Structural: a client cannot render green from a payload with no status."""
        client, paths, ids = route
        _break_semantic_search(monkeypatch)

        rec_id = _run_query(client, "root")["provenance_record_id"]
        detail = client.get(f"/api/provenance/{rec_id}").get_json()

        assert detail["leaves"], "the cited leaves are still listed"
        for leaf in detail["leaves"]:
            assert leaf["status"] is None, (
                f"sent a verdict it cannot support: {leaf['status']!r}"
            )
        blob = json.dumps(detail)
        for word in DISPLAY_VALUES:
            assert f'"{word}"' not in blob, f"{word!r} reached the client unattestably"
        assert detail["attestation_gap"], "must say WHY there is no verdict"

    def test_unattestable_summary_makes_no_claim(self, route, monkeypatch):
        client, paths, ids = route
        _break_semantic_search(monkeypatch)

        rec_id = _run_query(client, "root")["provenance_record_id"]
        summary = client.get(f"/api/provenance/{rec_id}").get_json()["summary"]

        assert "resolve" not in summary, summary
        assert "unchanged since trace" not in summary, summary
        assert "no elapsed check" in summary, summary


class TestTreeIntegrityIsASeparateClaim:
    def test_results_carry_content_hash_ok(self, route):
        client, paths, ids = route

        payload = _run_query(client)

        for r in payload["results"]:
            assert r["content_hash_ok"] is True

    def test_tampered_leaf_reads_false(self, route):
        client, paths, ids = route
        tampered = _tamper_a_leaf(paths["tree"])

        payload = _run_query(client, "tampered")

        hit = [r for r in payload["results"] if r["id"] == tampered]
        assert hit, "the tampered leaf should still be retrievable"
        assert hit[0]["content_hash_ok"] is False, (
            "content no longer hashes to its stored value — integrity must say so"
        )


class TestRocsTamperShowsNoGreenAnywhere:
    """The 2026-07-25 cold read, end to end.

    Edit a leaf, run the default path (keyword fallback), and assert the
    payloads a browser receives contain no basis for a green verdict — from
    either indicator. This is the regression that must never come back.
    """

    def test_no_green_from_either_indicator(self, route, monkeypatch):
        client, paths, ids = route
        _break_semantic_search(monkeypatch)
        tampered = _tamper_a_leaf(paths["tree"])

        payload = _run_query(client, "tampered")
        card = [r for r in payload["results"] if r["id"] == tampered][0]

        # 1. tree integrity: the tampered card must fail its own hash
        assert card["content_hash_ok"] is False

        # 2. retrieval trace: no verdict at all on a self-referential path
        detail = client.get(
            f"/api/provenance/{payload['provenance_record_id']}"
        ).get_json()
        assert detail["attestable"] is False
        assert all(leaf["status"] is None for leaf in detail["leaves"])
        assert "resolve" not in detail["summary"]


class TestScopeNotePerEmitter:
    def test_retrieval_only_note_does_not_mention_an_answer(self, route):
        client, paths, ids = route

        rec_id = _run_query(client)["provenance_record_id"]
        note = client.get(f"/api/provenance/{rec_id}").get_json()["scope_note"]

        assert note, "every record must carry its own scope note"
        assert "answer" not in note.lower(), (
            f"query/search have no generated answer; copy borrowed from a "
            f"generation path: {note!r}"
        )

    def test_generation_emitter_gets_answer_aware_copy(self, route):
        """run-validation DOES generate text, so its caveat differs."""
        from demo import server

        client, paths, ids = route
        note = server._scope_note("pcis.retrieval-trace/demo.run-validation")

        assert "answer" in note.lower() or "challenge" in note.lower(), note
        assert note != server._scope_note("pcis.retrieval-trace/demo.query")


class TestProvenanceDetail:
    def test_renders_display_vocabulary_never_wire_values(self, route):
        client, paths, ids = route
        rec_id = _run_query(client)["provenance_record_id"]

        detail = client.get(f"/api/provenance/{rec_id}").get_json()

        assert detail["leaves"], "a trace with cited leaves must list them"
        for leaf in detail["leaves"]:
            assert leaf["status"] in DISPLAY_VALUES, (
                f"wire value leaked to the client: {leaf['status']}"
            )
        blob = json.dumps(detail)
        for wire in WIRE_VALUES:
            assert f'"{wire}"' not in blob, f"wire value {wire!r} reached the client"

    def test_exposes_no_bare_pass_fail_field(self, route):
        """Structural: you cannot render a green chip from this payload."""
        client, paths, ids = route
        rec_id = _run_query(client)["provenance_record_id"]

        detail = client.get(f"/api/provenance/{rec_id}").get_json()

        for banned in ("ok", "valid", "verified", "passed"):
            assert banned not in detail, (
                f"{banned!r} invites exactly the bare chip the module bans"
            )

    def test_always_surfaces_whether_supersession_was_checked(self, route):
        client, paths, ids = route
        rec_id = _run_query(client)["provenance_record_id"]

        detail = client.get(f"/api/provenance/{rec_id}").get_json()

        assert "synapses_loaded" in detail
        assert isinstance(detail["synapses_loaded"], bool)

    def test_no_synapse_graph_reads_as_not_checked(self, route):
        """The demo dir here is empty, so there is genuinely no graph.

        core.knowledge_synapses.load_synapses would hand back a fully-formed
        EMPTY graph for this case, which would report synapses_loaded=True and
        claim a check that never happened.
        """
        client, paths, ids = route
        rec_id = _run_query(client)["provenance_record_id"]

        detail = client.get(f"/api/provenance/{rec_id}").get_json()

        assert detail["synapses_loaded"] is False

    def test_summary_never_claims_unchanged_while_reporting_drift(self, route):
        client, paths, ids = route
        rec_id = _run_query(client)["provenance_record_id"]

        # Edit a cited leaf's content after the trace — real drift.
        import knowledge_tree as kt

        tree = kt.load_tree(paths["tree"])
        for branch in tree["branches"].values():
            for leaf in branch["leaves"]:
                leaf["content"] = leaf["content"] + " EDITED AFTER TRACE"
        kt.save_tree(tree, paths["tree"])

        detail = client.get(f"/api/provenance/{rec_id}").get_json()

        assert "drifted" in detail["summary"]
        assert "unchanged" not in detail["summary"], (
            "reporting drift and claiming unchanged in one line is the bug "
            "this wording rule exists to prevent"
        )
        assert all(leaf["status"] == "drifted" for leaf in detail["leaves"])

    def test_unknown_record_id_is_404_not_a_blank_pass(self, route):
        client, paths, ids = route

        resp = client.get("/api/provenance/does-not-exist")

        assert resp.status_code == 404

    def test_survives_a_corrupt_synapse_file(self, route, tmp_path):
        """load_synapses sys.exit(1)s on corrupt JSON — that must never run
        inside a request, or a bad file takes the server down."""
        client, paths, ids = route
        rec_id = _run_query(client)["provenance_record_id"]

        syn = tmp_path / "demo_out" / "demo_synapses.json"
        syn.write_text("{not json at all", encoding="utf-8")

        resp = client.get(f"/api/provenance/{rec_id}")

        assert resp.status_code == 200, "a corrupt graph must degrade, not kill"
        assert resp.get_json()["synapses_loaded"] is False
