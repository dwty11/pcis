"""test_retrieval_trace_wiring.py — the five emitters actually trace.

The trace machinery already worked when called; nothing called it. These
tests are about the wiring: that retrieval through each of the five
approved emitters lands a record in the ledger, hashing the right copy of
the text, and that a ledger failure can never break retrieval.

THE IMPORTANT TEST IN EACH SECTION
==================================
``*_returns_normal_payload_when_ledger_write_fails``. Provenance logging is
observability, not the product. If it can take down `pcis search` or an
agent's memory lookup, it is worse than not having it. The honest cost of
swallowing is that coverage becomes unverifiable — so nothing anywhere
claims coverage, only that traced retrievals are traced.

WHICH COPY GETS HASHED
======================
The four search emitters — ``pcis search``, the agent plugin's
``pcis_search``, and the demo's ``/api/query`` and ``/api/search`` — hash
the INDEX copy that ``search()`` returned on the semantic path; that is the
text that was injected, and the reason a stale index is detectable at all.
Each also has a keyword fallback that reads the TREE, and each sets
``injection_source="tree"`` there so a self-referential re-verification is
never attested as a pass. ``api_run_validation`` hashes TREE content, because its
candidates come from ``load_tree()`` and never touch the index, so the
index-vs-tree staleness signal does not apply there; only post-trace drift
does.
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import patch

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, _ROOT)

VECTOR = [0.5, 0.25, 0.125, 0.0625]
# Long enough that a 200-char clip would lose the trailing qualifier — which
# is the correctness hazard, not a cosmetic one.
LONG_CONTENT = (
    "Deploys are safe on Fridays for this service because the rollback path "
    "is automated and has been exercised in the last quarter, and the on-call "
    "rotation is staffed through the weekend with a documented escalation "
    "path, and the migration is backwards compatible in both directions, "
    "UNLESS the schema migration is still mid-flight, in which case a Friday "
    "deploy is explicitly forbidden."
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A real tree + real index under PCIS_BASE_DIR. Returns (kt, paths, ids)."""
    import knowledge_tree as kt
    import core.knowledge_tree as core_kt
    import knowledge_search as ks
    import core.knowledge_search as core_ks

    monkeypatch.setenv("PCIS_BASE_DIR", str(tmp_path))
    monkeypatch.delenv("PCIS_TRACE_RETRIEVAL", raising=False)
    data = tmp_path / "data"
    data.mkdir()
    tree_file = data / "tree.json"

    tree = {"branches": {}, "root_hash": ""}
    long_id = kt.add_knowledge(tree, "lessons", LONG_CONTENT, source="test", confidence=0.9)
    short_id = kt.add_knowledge(tree, "technical", "the root moves on every commit")
    kt.save_tree(tree, str(tree_file))

    saved = kt.load_tree(str(tree_file))
    by_id = {
        leaf["id"]: (bname, leaf)
        for bname, b in saved["branches"].items()
        for leaf in b["leaves"]
    }
    index = {
        "model": "nomic-embed-text", "dimensions": 4, "created": "c",
        "last_reindex": "c", "leaf_count": 2, "embeddings": {},
    }
    for lid, (bname, leaf) in by_id.items():
        index["embeddings"][lid] = {
            "branch": bname, "content": leaf["content"], "source": leaf.get("source", ""),
            "confidence": leaf["confidence"], "created": leaf["created"],
            "vector": list(VECTOR),
        }
    index_file = data / "search-index.json"
    index_file.write_text(json.dumps(index), encoding="utf-8")

    for mod in (ks, core_ks):
        monkeypatch.setattr(mod, "INDEX_FILE", str(index_file))
        monkeypatch.setattr(mod, "TREE_FILE", str(tree_file))
        monkeypatch.setattr(mod, "get_embedding", lambda t, model=None: list(VECTOR))
    for mod in (kt, core_kt):
        monkeypatch.setattr(mod, "BASE_DIR", str(tmp_path))
        monkeypatch.setattr(mod, "TREE_FILE", str(tree_file))

    return kt, {"base": tmp_path, "tree": str(tree_file)}, {
        "long": long_id, "short": short_id
    }


def _ledger(base):
    from provenance_ledger import load_ledger

    return load_ledger(str(base / "data" / "provenance-ledger.jsonl"))


def _break_ledger(monkeypatch):
    """Make every ledger append raise, as a full disk or bad perms would."""
    import provenance_ledger

    def boom(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(provenance_ledger, "append_record", boom)


# ===========================================================================
# The helper
# ===========================================================================


class TestEmitRetrievalTrace:
    def test_writes_a_record_hashing_the_index_copy(self, env):
        from core.knowledge_search import search
        from retrieval_trace import content_hash, emit_retrieval_trace

        kt, paths, ids = env
        results = search("deploys", top_k=5)
        assert results, "fixture produced no search results"

        rec = emit_retrieval_trace(
            sink="pcis.retrieval-trace/test",
            search_results=results,
            answer_text="rendered block",
        )

        assert rec is not None
        persisted = _ledger(paths["base"])
        assert len(persisted) == 1
        # The hash is of the FULL index copy, not a truncation of it.
        assert persisted[0].retrieval.leaf_content_hashes[ids["long"]] == \
            content_hash(LONG_CONTENT)

    def test_no_trace_when_nothing_was_retrieved(self, env):
        from retrieval_trace import emit_retrieval_trace

        kt, paths, ids = env
        rec = emit_retrieval_trace(
            sink="s", search_results=[], answer_text="No results found."
        )

        assert rec is None
        assert not (paths["base"] / "data" / "provenance-ledger.jsonl").exists()

    def test_disabled_by_env_var(self, env, monkeypatch):
        from core.knowledge_search import search
        from retrieval_trace import emit_retrieval_trace

        kt, paths, ids = env
        monkeypatch.setenv("PCIS_TRACE_RETRIEVAL", "0")

        rec = emit_retrieval_trace(
            sink="s", search_results=search("deploys", top_k=5), answer_text="x"
        )

        assert rec is None
        assert not (paths["base"] / "data" / "provenance-ledger.jsonl").exists()

    def test_records_render_truncation_in_extras(self, env):
        from core.knowledge_search import search
        from retrieval_trace import emit_retrieval_trace

        kt, paths, ids = env
        emit_retrieval_trace(
            sink="s", search_results=search("deploys", top_k=5),
            answer_text="x", rendered_truncated_to=150,
        )

        block = _ledger(paths["base"])[0].retrieval
        assert block.extras["rendered_truncated_to"] == 150

    def test_no_truncation_key_when_nothing_was_truncated(self, env):
        from core.knowledge_search import search
        from retrieval_trace import emit_retrieval_trace

        kt, paths, ids = env
        emit_retrieval_trace(
            sink="s", search_results=search("deploys", top_k=5), answer_text="x"
        )

        assert "rendered_truncated_to" not in _ledger(paths["base"])[0].retrieval.extras

    def test_swallows_ledger_failure_and_warns(self, env, monkeypatch, capsys):
        from core.knowledge_search import search
        from retrieval_trace import emit_retrieval_trace

        kt, paths, ids = env
        _break_ledger(monkeypatch)

        rec = emit_retrieval_trace(
            sink="s", search_results=search("deploys", top_k=5), answer_text="x"
        )

        assert rec is None
        assert "provenance" in capsys.readouterr().err.lower()

    def test_swallows_a_tree_load_failure(self, env, monkeypatch, capsys):
        import retrieval_trace
        from core.knowledge_search import search
        from retrieval_trace import emit_retrieval_trace

        kt, paths, ids = env
        results = search("deploys", top_k=5)
        monkeypatch.setattr(
            retrieval_trace, "load_tree",
            lambda *a, **k: (_ for _ in ()).throw(OSError("tree unreadable")),
        )

        assert emit_retrieval_trace(sink="s", search_results=results, answer_text="x") is None
        assert capsys.readouterr().err

    def test_accepts_an_explicit_injection_for_generative_callers(self, env):
        from retrieval_trace import content_hash, emit_retrieval_trace

        kt, paths, ids = env
        rec = emit_retrieval_trace(
            sink="pcis.retrieval-trace/test-gen",
            injection=[(ids["short"], "the root moves on every commit")],
            answer_text="a model challenge",
            producer_model="qwen3:14b",
        )

        assert rec is not None
        block = _ledger(paths["base"])[0].retrieval
        assert block.producer_model == "qwen3:14b"
        assert block.injected_leaf_ids == [ids["short"]]
        assert block.answer_text == "a model challenge"

    def test_timestamp_is_utc_iso8601_with_microseconds(self, env):
        """Settled contract: UTC, +00:00 form, microsecond precision.

        Microseconds are not optional — truncating to seconds collapses
        distinct events into sort ties, and a bare ``.isoformat()`` drops the
        fractional part whenever microsecond happens to be exactly 0.
        """
        import re
        from datetime import datetime

        from core.knowledge_search import search
        from retrieval_trace import emit_retrieval_trace

        kt, paths, ids = env
        emit_retrieval_trace(
            sink="s", search_results=search("deploys", top_k=5), answer_text="x"
        )

        ts = _ledger(paths["base"])[0].timestamp
        assert datetime.fromisoformat(ts).utcoffset().total_seconds() == 0, \
            f"not UTC: {ts}"
        assert ts.endswith("+00:00"), f"expected +00:00 form, got {ts}"
        assert re.search(r"\.\d{6}\+00:00$", ts), (
            f"expected 6-digit microseconds, got {ts}"
        )

    def test_timestamp_keeps_microseconds_when_they_are_zero(self, env, monkeypatch):
        """The edge a bare .isoformat() silently loses."""
        import re
        from datetime import datetime, timezone

        import retrieval_trace
        from core.knowledge_search import search

        kt, paths, ids = env

        class _FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 7, 25, 12, 0, 0, 0, tzinfo=timezone.utc)

        monkeypatch.setattr(retrieval_trace, "datetime", _FixedDatetime)
        retrieval_trace.emit_retrieval_trace(
            sink="s", search_results=search("deploys", top_k=5), answer_text="x"
        )

        ts = _ledger(paths["base"])[0].timestamp
        assert ts == "2026-07-25T12:00:00.000000+00:00", ts
        assert re.search(r"\.\d{6}\+00:00$", ts)


# ===========================================================================
# 1. agent-plugin pcis_search
# ===========================================================================


def _load_plugin():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "pcis_agent_plugin_wiring", os.path.join(_ROOT, "agent-plugin", "plugin.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestAgentPluginSearch:
    def test_no_longer_truncates_content(self, env):
        """A 200-char clip handed to an AGENT can drop a trailing qualifier —
        here, the 'UNLESS ... explicitly forbidden' that reverses the claim.
        A human sees an ellipsis; an agent cannot."""
        kt, paths, ids = env
        plugin = _load_plugin()

        rows = plugin.pcis_search("deploys", config={"base_dir": str(paths["base"])})

        row = next(r for r in rows if r["leaf_id"] == ids["long"])
        assert row["content"] == LONG_CONTENT
        assert "explicitly forbidden" in row["content"], (
            "the reversing qualifier must survive — this is the hazard"
        )

    def test_writes_a_trace(self, env):
        from retrieval_trace import content_hash

        kt, paths, ids = env
        plugin = _load_plugin()

        plugin.pcis_search("deploys", config={"base_dir": str(paths["base"])})

        persisted = _ledger(paths["base"])
        assert len(persisted) == 1
        block = persisted[0].retrieval
        assert block.sink == "pcis.retrieval-trace/agent-plugin.search"
        assert block.producer_model is None, "no model generated anything here"
        assert block.leaf_content_hashes[ids["long"]] == content_hash(LONG_CONTENT)

    def test_returns_normal_payload_when_ledger_write_fails(
        self, env, monkeypatch, capsys
    ):
        """THE important one: provenance must never break memory lookup."""
        kt, paths, ids = env
        _break_ledger(monkeypatch)
        plugin = _load_plugin()

        rows = plugin.pcis_search("deploys", config={"base_dir": str(paths["base"])})

        assert rows, "retrieval must still return results"
        assert any(r["leaf_id"] == ids["long"] for r in rows)
        assert capsys.readouterr().err, "the failure must be visible, not silent"

    def test_no_trace_on_zero_results(self, env, monkeypatch):
        import core.knowledge_search as core_ks

        kt, paths, ids = env
        monkeypatch.setattr(core_ks, "search", lambda *a, **k: [])
        plugin = _load_plugin()

        assert plugin.pcis_search("nothing", config={"base_dir": str(paths["base"])}) == []
        assert not (paths["base"] / "data" / "provenance-ledger.jsonl").exists()

    def test_env_var_disables_tracing(self, env, monkeypatch):
        kt, paths, ids = env
        monkeypatch.setenv("PCIS_TRACE_RETRIEVAL", "0")
        plugin = _load_plugin()

        assert plugin.pcis_search("deploys", config={"base_dir": str(paths["base"])})
        assert not (paths["base"] / "data" / "provenance-ledger.jsonl").exists()


# ===========================================================================
# 2. cli cmd_search
# ===========================================================================


class TestCliSearch:
    def _args(self, query="deploys"):
        import argparse

        return argparse.Namespace(query=query, top_k=5, branch=None, base_dir=None)

    def test_keeps_display_truncation(self, env, capsys):
        """A human reader sees a clipped line and knows it is clipped; the
        trace still hashes the full text."""
        from pcis import cli

        kt, paths, ids = env
        cli.cmd_search(self._args())

        out = capsys.readouterr().out
        assert "explicitly forbidden" not in out, "display should stay truncated"
        assert LONG_CONTENT[:80] in out

    def test_writes_a_trace_hashing_full_content(self, env, capsys):
        from pcis import cli
        from retrieval_trace import content_hash

        kt, paths, ids = env
        cli.cmd_search(self._args())
        capsys.readouterr()

        persisted = _ledger(paths["base"])
        assert len(persisted) == 1
        block = persisted[0].retrieval
        assert block.sink == "pcis.retrieval-trace/cli.search"
        assert block.leaf_content_hashes[ids["long"]] == content_hash(LONG_CONTENT)
        assert block.extras["rendered_truncated_to"] == 150

    def test_still_prints_results_when_ledger_write_fails(
        self, env, monkeypatch, capsys
    ):
        from pcis import cli

        kt, paths, ids = env
        _break_ledger(monkeypatch)

        cli.cmd_search(self._args())

        captured = capsys.readouterr()
        assert "Found 2 result(s)" in captured.out, "search output must survive"
        assert captured.err, "the provenance failure must be visible"

    def test_no_trace_on_zero_results(self, env, monkeypatch, capsys):
        import knowledge_search as ks
        from pcis import cli

        kt, paths, ids = env
        monkeypatch.setattr(ks, "search", lambda *a, **k: [])
        cli.cmd_search(self._args("nothing"))

        assert "No results found." in capsys.readouterr().out
        assert not (paths["base"] / "data" / "provenance-ledger.jsonl").exists()


# ===========================================================================
# 3. demo api_run_validation
# ===========================================================================


class _FakeOllama:
    """Context-manager response matching what the route reads."""

    def __init__(self, text):
        self._text = text

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps({"response": self._text}).encode()


class TestRunValidationRoute:
    @pytest.fixture
    def route(self, env, monkeypatch, tmp_path):
        from demo import server

        kt, paths, ids = env
        monkeypatch.setattr(server, "DEMO_TREE_FILE", paths["tree"])
        # Keep the route's own JSON artifact out of the repo.
        monkeypatch.setattr(server, "DEMO_DIR", str(tmp_path / "demo_out"))
        os.makedirs(str(tmp_path / "demo_out"), exist_ok=True)
        return server.app.test_client(), paths, ids

    def test_writes_one_record_per_challenged_leaf(self, route, monkeypatch):
        client, paths, ids = route
        # Only 2 leaves exist, so the route's sample of 3 needs a third.
        import knowledge_tree as kt

        tree = kt.load_tree(paths["tree"])
        kt.add_knowledge(tree, "technical", "a third claim to challenge")
        kt.save_tree(tree, paths["tree"])

        with patch("urllib.request.urlopen", return_value=_FakeOllama("a challenge")):
            resp = client.post("/api/run-validation")

        assert resp.status_code == 200, resp.get_json()
        persisted = _ledger(paths["base"])
        assert len(persisted) == 3, (
            f"one model call per leaf means one record per leaf, got {len(persisted)}"
        )
        for rec in persisted:
            assert len(rec.retrieval.injected_leaf_ids) == 1, (
                "each generation had exactly one leaf in its prompt"
            )
            assert rec.retrieval.producer_model == "qwen3:14b"
            assert rec.retrieval.answer_text == "a challenge"
            assert rec.retrieval.sink == "pcis.retrieval-trace/demo.run-validation"

    def test_anchors_on_derived_root_not_stored_value(self, route, monkeypatch):
        import knowledge_tree as kt

        client, paths, ids = route
        tree = kt.load_tree(paths["tree"])
        kt.add_knowledge(tree, "technical", "a third claim to challenge")
        # Corrupt the STORED root so a derived anchor is distinguishable.
        tree["root_hash"] = "d" * 64
        with open(paths["tree"], "w", encoding="utf-8") as f:
            json.dump(tree, f)

        with patch("urllib.request.urlopen", return_value=_FakeOllama("a challenge")):
            client.post("/api/run-validation")

        expected = kt.compute_root_hash(kt.load_tree(paths["tree"]))
        for rec in _ledger(paths["base"]):
            assert rec.retrieval.tree_root_at_trace == expected
            assert rec.retrieval.tree_root_at_trace != "d" * 64

    def test_before_and_after_are_derived_the_same_way(self, route):
        """A difference in DERIVATION must not be captioned as change over TIME.

        The first fix made `after` a fresh compute_root_hash while `before`
        stayed the STORED root_hash field. With a stale stored root the two
        differ for that reason alone, and the UI renders a before→after
        transition — reporting a change that never happened.
        """
        import knowledge_tree as kt

        client, paths, ids = route
        tree = kt.load_tree(paths["tree"])
        kt.add_knowledge(tree, "technical", "a third claim to challenge")
        # a STALE stored root: the field disagrees with the tree it describes
        tree["root_hash"] = "d" * 64
        with open(paths["tree"], "w", encoding="utf-8") as f:
            json.dump(tree, f)

        with patch("urllib.request.urlopen", return_value=_FakeOllama("a challenge")):
            resp = client.post("/api/run-validation")

        data = resp.get_json()
        assert data["merkle_root_before"] != "d" * 64, (
            "before must be derived, not read from the stale stored field"
        )
        # This route does not write the tree, so it must not name an after-root
        # at all. The projection is still checked against `before` for the
        # original property: a stale STORED root must not make the two ends
        # disagree, because that difference is derivation, not time.
        assert "merkle_root_after" not in data, (
            "no write occurred, so an after-root would name an observation "
            "nobody made — the key must be absent, not merely equal"
        )
        assert data["merkle_root_before"] == data["merkle_root_projected"], (
            "nothing was committed; a stale stored root must not manufacture "
            "a before/projected difference"
        )
        assert data["tree_written"] is False
        # No root_claim assertion here: this route's body is discarded by the
        # client, which re-fetches /api/external-validation to render. The
        # protection that matters at THIS end is that the false pair
        # (after-root + no write) is not expressible in the artifact at all,
        # which the two assertions above check.

    def test_merkle_root_after_is_measured_not_copied(self, route, monkeypatch):
        """`merkle_root_after` was assigned `merkle_root_before` verbatim.

        The field name asserted a post-state nobody measured, and the UI's
        "root unchanged" branch was therefore always taken — the transition
        branch was unreachable. A future change that DID commit leaves would
        have reported unchanged and nobody would have known.

        Here a leaf is committed DURING the run, so before and after must differ.
        """
        import knowledge_tree as kt

        client, paths, ids = route
        tree = kt.load_tree(paths["tree"])
        kt.add_knowledge(tree, "technical", "a third claim to challenge")
        kt.save_tree(tree, paths["tree"])

        committed = {"done": False}

        class _CommittingOllama(_FakeOllama):
            def read(self):
                # simulate the run committing a leaf partway through
                if not committed["done"]:
                    t = kt.load_tree(paths["tree"])
                    kt.add_knowledge(t, "lessons", "committed mid-run")
                    kt.save_tree(t, paths["tree"])
                    committed["done"] = True
                return super().read()

        with patch("urllib.request.urlopen", return_value=_CommittingOllama("a challenge")):
            resp = client.post("/api/run-validation")

        data = resp.get_json()
        assert committed["done"], "fixture must actually commit something"
        assert data["merkle_root_after"] != data["merkle_root_before"], (
            "a leaf was committed during the run; the after-root must reflect it"
        )
        assert data["merkle_root_after"] == kt.compute_root_hash(
            kt.load_tree(paths["tree"])
        ), "after-root must be derived from the tree as it stands at the end"

    def test_route_still_succeeds_when_ledger_write_fails(self, route, monkeypatch):
        import knowledge_tree as kt

        client, paths, ids = route
        tree = kt.load_tree(paths["tree"])
        kt.add_knowledge(tree, "technical", "a third claim to challenge")
        kt.save_tree(tree, paths["tree"])
        _break_ledger(monkeypatch)

        with patch("urllib.request.urlopen", return_value=_FakeOllama("a challenge")):
            resp = client.post("/api/run-validation")

        assert resp.status_code == 200, "validation must not fail because logging did"
        assert len(resp.get_json()["counters"]) == 3


# ===========================================================================
# 3b. ATTESTABILITY — can this trace's re-verification prove anything?
# ===========================================================================
#
# Found by a cold reader tampering a leaf (2026-07-25). On the demo's keyword
# fallback the injected content is read from the TREE and re-verified against
# the TREE, so the comparison is self-referential and structurally cannot fail
# — the module docstring names this exact anti-pattern. A tamper made BEFORE
# the trace is baked into the record as ground truth and reads "resolves".
#
# The distinction is same-ARTIFACT, not same-request: the record is written and
# verified in separate requests, but from one source. It is a property of the
# record plus the tree, so it belongs here rather than in one caller's UI.


class TestAttestability:
    def _emit(self, env, **kw):
        from core.knowledge_search import search
        from retrieval_trace import emit_retrieval_trace

        return emit_retrieval_trace(
            sink="s", search_results=search("deploys", top_k=5), answer_text="x", **kw
        )

    def test_index_sourced_is_attestable(self, env):
        """search() reads only the index, never the tree — a real comparison."""
        import knowledge_tree as kt
        from retrieval_trace import verify_retrieval

        _, paths, _ = env
        rec = self._emit(env)
        res = verify_retrieval(rec, tree=kt.load_tree(paths["tree"]))

        assert res["injection_source"] == "index"
        assert res["attestable"] is True
        assert res["attestation_gap"] is None

    def test_tree_sourced_with_unmoved_root_is_NOT_attestable(self, env):
        """The self-referential case: same artifact in and out, tree unchanged."""
        import knowledge_tree as kt
        from retrieval_trace import emit_retrieval_trace, verify_retrieval

        _, paths, ids = env
        tree = kt.load_tree(paths["tree"])
        leaf = tree["branches"]["technical"]["leaves"][0]
        rec = emit_retrieval_trace(
            sink="s", injection=[(leaf["id"], leaf["content"])],
            answer_text="x", tree=tree, extras={"injection_source": "tree"},
        )
        res = verify_retrieval(rec, tree=kt.load_tree(paths["tree"]))

        assert res["injection_source"] == "tree"
        assert res["attestable"] is False, (
            "comparing the tree to itself cannot fail; it must not be presented "
            "as a passing check"
        )
        assert "itself" in res["attestation_gap"]

    def test_tree_sourced_becomes_attestable_once_the_root_moves(self, env):
        """Elapsed time is what gives a tree-sourced trace purchase."""
        import knowledge_tree as kt
        from retrieval_trace import emit_retrieval_trace, verify_retrieval

        _, paths, ids = env
        tree = kt.load_tree(paths["tree"])
        leaf = tree["branches"]["technical"]["leaves"][0]
        rec = emit_retrieval_trace(
            sink="s", injection=[(leaf["id"], leaf["content"])],
            answer_text="x", tree=tree, extras={"injection_source": "tree"},
        )
        # the tree moves on: an unrelated leaf is added
        tree2 = kt.load_tree(paths["tree"])
        kt.add_knowledge(tree2, "lessons", "something new entirely")
        kt.save_tree(tree2, paths["tree"])

        res = verify_retrieval(rec, tree=kt.load_tree(paths["tree"]))
        assert res["root_state"] == "stale"
        assert res["attestable"] is True
        assert res["re_verification"][leaf["id"]] == "pass"

    def test_unrecorded_source_fails_toward_friction(self, env):
        """An old record with no injection_source cannot be assumed independent."""
        import knowledge_tree as kt
        from retrieval_trace import emit_retrieval_trace, verify_retrieval

        _, paths, ids = env
        tree = kt.load_tree(paths["tree"])
        leaf = tree["branches"]["technical"]["leaves"][0]
        rec = emit_retrieval_trace(
            sink="s", injection=[(leaf["id"], leaf["content"])],
            answer_text="x", tree=tree,
        )
        res = verify_retrieval(rec, tree=kt.load_tree(paths["tree"]))

        assert res["injection_source"] is None
        assert res["attestable"] is False

    def test_summarize_does_not_claim_a_pass_it_cannot_make(self, env):
        """The exact line the cold read saw: 'N/N resolve, unchanged since trace'."""
        import knowledge_tree as kt
        from retrieval_trace import emit_retrieval_trace, summarize, verify_retrieval

        _, paths, ids = env
        tree = kt.load_tree(paths["tree"])
        leaf = tree["branches"]["technical"]["leaves"][0]
        rec = emit_retrieval_trace(
            sink="s", injection=[(leaf["id"], leaf["content"])],
            answer_text="x", tree=tree, extras={"injection_source": "tree"},
        )
        line = summarize(verify_retrieval(rec, tree=kt.load_tree(paths["tree"])))

        assert "resolve" not in line, f"claimed a pass it cannot make: {line}"
        assert "unchanged since trace" not in line, line
        assert "no elapsed check" in line, line

    def test_emitter_labels_search_results_as_index_sourced(self, env):
        """The emitter knows: search() provably reads the index, never the tree."""
        rec = self._emit(env)
        assert rec.retrieval.extras["injection_source"] == "index"

    def test_explicit_caller_source_is_not_overridden(self, env):
        from core.knowledge_search import search
        from retrieval_trace import emit_retrieval_trace

        rec = emit_retrieval_trace(
            sink="s", search_results=search("deploys", top_k=5), answer_text="x",
            extras={"injection_source": "tree"},
        )
        assert rec.retrieval.extras["injection_source"] == "tree"


# ===========================================================================
# 4. emit_retrieval_trace extras passthrough
# ===========================================================================


class TestExtrasPassthrough:
    """``extras`` is V1 forward-compat plumbing — free-form by design.

    The emitter previously hardcoded it to ``rendered_truncated_to`` only, so
    a caller had no way to record anything else without dropping to
    ``log_retrieval`` and losing the never-raises policy that makes provenance
    safe to wire into a request path.
    """

    def test_caller_extras_reach_the_record(self, env):
        from core.knowledge_search import search
        from retrieval_trace import emit_retrieval_trace

        kt, paths, ids = env
        emit_retrieval_trace(
            sink="s",
            search_results=search("deploys", top_k=5),
            answer_text="x",
            extras={"retrieval_mode": "semantic"},
        )

        assert _ledger(paths["base"])[0].retrieval.extras["retrieval_mode"] == "semantic"

    def test_caller_extras_merge_with_rendered_truncated_to(self, env):
        """Neither key may clobber the other — they are independent facts."""
        from core.knowledge_search import search
        from retrieval_trace import emit_retrieval_trace

        kt, paths, ids = env
        emit_retrieval_trace(
            sink="s",
            search_results=search("deploys", top_k=5),
            answer_text="x",
            rendered_truncated_to=200,
            extras={"retrieval_mode": "keyword"},
        )

        extras = _ledger(paths["base"])[0].retrieval.extras
        assert extras["rendered_truncated_to"] == 200
        assert extras["retrieval_mode"] == "keyword"

    def test_omitting_extras_adds_only_the_derived_source(self, env):
        """No caller extras means extras holds exactly what the emitter itself
        can prove — the injection source — and nothing invented."""
        from core.knowledge_search import search
        from retrieval_trace import emit_retrieval_trace

        kt, paths, ids = env
        emit_retrieval_trace(
            sink="s", search_results=search("deploys", top_k=5), answer_text="x"
        )

        assert _ledger(paths["base"])[0].retrieval.extras == {"injection_source": "index"}


# ===========================================================================
# 5. demo /api/query  +  /api/search  — the two browser-facing retrievals
# ===========================================================================
#
# Gap 2 from the observability review: /api/query is the path users click and
# it emitted nothing. /api/search is the second retrieval surface, backing the
# tab that sits LEFT of Query in the nav — the likelier first click, and it
# emitted nothing either.
#
# The keyword-fallback tests are the load-bearing ones. A fresh clone has no
# search index (demo/demo_search_index.json is gitignored AND absent from
# HEAD), so the fallback IS the default path for a stranger, and it is exactly
# the path the run-validation emitter could never reach with Ollama down.


class _RouteBase:
    @pytest.fixture
    def route(self, env, monkeypatch, tmp_path):
        from demo import server

        kt, paths, ids = env
        monkeypatch.setattr(server, "DEMO_TREE_FILE", paths["tree"])
        monkeypatch.setattr(server, "DEMO_DIR", str(tmp_path / "demo_out"))
        os.makedirs(str(tmp_path / "demo_out"), exist_ok=True)
        return server.app.test_client(), paths, ids


def _break_semantic_search(monkeypatch):
    """Force the keyword fallback, as a missing index or dead Ollama would."""
    import knowledge_search
    import core.knowledge_search as core_ks

    def boom(*a, **k):
        raise RuntimeError("ollama is not running")

    for mod in (knowledge_search, core_ks):
        monkeypatch.setattr(mod, "search", boom)


class TestQueryRoute(_RouteBase):
    def test_emits_one_record_for_the_whole_result_set(self, route):
        client, paths, ids = route

        resp = client.post("/api/query", json={"query": "deploys"})

        assert resp.status_code == 200
        persisted = _ledger(paths["base"])
        assert len(persisted) == 1, (
            f"one retrieval is one record, got {len(persisted)}"
        )
        block = persisted[0].retrieval
        assert block.sink == "pcis.retrieval-trace/demo.query"
        returned = [r["id"] for r in resp.get_json()["results"]]
        assert block.injected_leaf_ids == returned, (
            "the record must name exactly the leaves the browser was shown, in rank order"
        )

    def test_records_semantic_mode(self, route):
        client, paths, ids = route

        client.post("/api/query", json={"query": "deploys"})

        assert _ledger(paths["base"])[0].retrieval.extras["retrieval_mode"] == "semantic"

    def test_emits_on_the_keyword_fallback(self, route, monkeypatch):
        """The fresh-clone default path — no index, no Ollama."""
        client, paths, ids = route
        _break_semantic_search(monkeypatch)

        resp = client.post("/api/query", json={"query": "root"})

        assert resp.status_code == 200
        assert resp.get_json()["results"], "fixture must actually match something"
        persisted = _ledger(paths["base"])
        assert len(persisted) == 1, "a keyword-fallback retrieval is still a retrieval"
        assert persisted[0].retrieval.extras["retrieval_mode"] == "keyword"

    def test_no_results_writes_no_record(self, route, monkeypatch):
        """Nothing was retrieved, so there is nothing to attest.

        Forced onto the keyword path: the fixture's fake embedder returns one
        constant vector, so the semantic path matches everything and can never
        produce an empty result set.
        """
        client, paths, ids = route
        _break_semantic_search(monkeypatch)

        resp = client.post("/api/query", json={"query": "zzzznomatchzzzz"})

        assert resp.get_json()["results"] == []
        assert _ledger(paths["base"]) == []

    def test_producer_model_is_none(self, route):
        """No model produced an answer here; the record must not imply one."""
        client, paths, ids = route

        client.post("/api/query", json={"query": "deploys"})

        assert _ledger(paths["base"])[0].retrieval.producer_model is None

    def test_returns_normal_payload_when_ledger_write_fails(self, route, monkeypatch):
        client, paths, ids = route
        _break_ledger(monkeypatch)

        resp = client.post("/api/query", json={"query": "deploys"})

        assert resp.status_code == 200, "search must not fail because logging did"
        assert resp.get_json()["results"], "results must survive a ledger failure"


class TestSearchRoute(_RouteBase):
    def test_emits_one_record_for_the_whole_result_set(self, route):
        client, paths, ids = route

        resp = client.post("/api/search", json={"query": "deploys"})

        assert resp.status_code == 200
        persisted = _ledger(paths["base"])
        assert len(persisted) == 1
        block = persisted[0].retrieval
        assert block.sink == "pcis.retrieval-trace/demo.search"
        returned = [r["id"] for r in resp.get_json()["results"]]
        assert block.injected_leaf_ids == returned

    def test_emits_on_the_substring_fallback(self, route, monkeypatch):
        client, paths, ids = route
        _break_semantic_search(monkeypatch)

        resp = client.post("/api/search", json={"query": "root"})

        assert resp.get_json()["results"], "fixture must actually match something"
        persisted = _ledger(paths["base"])
        assert len(persisted) == 1
        assert persisted[0].retrieval.extras["retrieval_mode"] == "keyword"

    def test_no_results_writes_no_record(self, route, monkeypatch):
        """See TestQueryRoute.test_no_results_writes_no_record for why the
        semantic path cannot produce an empty set under this fixture."""
        client, paths, ids = route
        _break_semantic_search(monkeypatch)

        resp = client.post("/api/search", json={"query": "zzzznomatchzzzz"})

        assert resp.get_json()["results"] == []
        assert _ledger(paths["base"]) == []

    def test_returns_normal_payload_when_ledger_write_fails(self, route, monkeypatch):
        client, paths, ids = route
        _break_ledger(monkeypatch)

        resp = client.post("/api/search", json={"query": "deploys"})

        assert resp.status_code == 200, "search must not fail because logging did"
        assert resp.get_json()["results"]
