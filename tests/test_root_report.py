"""test_root_report.py — an artifact must not be able to name a root the tree never had.

FOUND BY A COLD READ (2026-07-27), one layer over the fix that was supposed to
prevent it. With a stub model answering 5/5, the validator wrote:

    tree_written:       false
    merkle_root_before: 07dd20bb...
    merkle_root_after:  9fbc8aa1...      <- a root the tree never had

and the dashboard, keying only on `before !== after`, rendered
"MERKLE ROOT TRANSITION 07dd20bb -> 9fbc8aa1". The console line had been
carefully labelled "(projected — tree not written)". The FIELD NAME and the
CONSUMER had not. A claim spanning three sites, fixed at one.

Two supports failed in the same way:

  - a comment asserted that `tree_written: false` "tells a consumer this is a
    projection". No consumer read it. The flag existed and did nothing.
  - a test asserted `tree_written is False` while the value was a hardcoded
    literal. Injecting a real tree write left the literal untouched and the test
    still passed: it checked the label, never the fact.

THE SHAPE OF THE FIX
====================
Not a better caption and not a third flag. Two subtractions:

  1. `tree_written` is DERIVED from the file's bytes before and after. A literal
     can claim anything; a value computed from an observation cannot claim a
     write that did not occur.
  2. The payload NEVER CARRIES an `merkle_root_after` key unless a write was
     observed. A consumer cannot render a transition from a field that is not
     there. Where no write happened the projection is emitted under a name that
     says so.

The point is not that the artifact now tells the truth. It is that the false
statement is no longer expressible.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, _ROOT)


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── 1. the flag must come from the file, not from a literal ──


def test_tree_written_is_false_when_the_file_is_untouched(tmp_path):
    from core.root_report import build_root_report, digest_file

    tree_file = tmp_path / "tree.json"
    before = _write(tree_file, {"branches": {}})

    report = build_root_report(
        root_before="aaa", root_projected="bbb",
        tree_path=str(tree_file), digest_before=before,
    )

    assert report["tree_written"] is False


def test_tree_written_flips_when_a_write_actually_happens(tmp_path):
    """Roc's test: inject a real write, and the flag must follow the bytes.

    The literal version of this passed with a real write in place, which is
    what made it worthless.
    """
    from core.root_report import build_root_report

    tree_file = tmp_path / "tree.json"
    before = _write(tree_file, {"branches": {}})
    _write(tree_file, {"branches": {"x": {"leaves": []}}})  # the injected write

    report = build_root_report(
        root_before="aaa", root_projected="bbb",
        tree_path=str(tree_file), digest_before=before,
    )

    assert report["tree_written"] is True, (
        "the flag was a hardcoded literal; a real write left it saying false"
    )


def test_a_missing_tree_file_is_not_reported_as_a_write(tmp_path):
    from core.root_report import build_root_report

    report = build_root_report(
        root_before="aaa", root_projected="bbb",
        tree_path=str(tmp_path / "gone.json"), digest_before=None,
    )

    assert report["tree_written"] is False


# ── 2. the after-root must not exist unless it was observed ──


def test_no_after_root_key_when_nothing_was_written(tmp_path):
    from core.root_report import build_root_report

    tree_file = tmp_path / "tree.json"
    before = _write(tree_file, {"branches": {}})

    report = build_root_report(
        root_before="aaa", root_projected="bbb",
        tree_path=str(tree_file), digest_before=before,
    )

    assert "merkle_root_after" not in report, (
        "a consumer renders a transition from before+after; the false statement "
        "must be inexpressible, not merely discouraged"
    )
    assert report["merkle_root_projected"] == "bbb"


def test_after_root_appears_only_when_a_write_was_observed(tmp_path):
    from core.root_report import build_root_report

    tree_file = tmp_path / "tree.json"
    before = _write(tree_file, {"branches": {}})
    _write(tree_file, {"branches": {"x": {"leaves": []}}})

    report = build_root_report(
        root_before="aaa", root_projected="bbb",
        tree_path=str(tree_file), digest_before=before,
    )

    assert report["merkle_root_after"] == "bbb"
    assert "merkle_root_projected" not in report


# ── 3. the verdict is derived once, server-side, not inferred by the client ──


def test_claim_kind_projected_when_nothing_written(tmp_path):
    from core.root_report import root_claim

    claim = root_claim({
        "merkle_root_before": "aaa", "merkle_root_projected": "bbb",
        "tree_written": False,
    })

    assert claim["kind"] == "projected"
    assert claim["before"] == "aaa" and claim["projected"] == "bbb"
    assert "after" not in claim


def test_claim_kind_transition_only_with_an_observed_write():
    from core.root_report import root_claim

    claim = root_claim({
        "merkle_root_before": "aaa", "merkle_root_after": "bbb",
        "tree_written": True,
    })

    assert claim["kind"] == "transition"


def test_claim_refuses_transition_when_after_is_present_but_no_write(tmp_path):
    """The exact defect: an after-root beside tree_written false.

    A legacy artifact can still carry that pair. The verdict must not honour it.
    """
    from core.root_report import root_claim

    claim = root_claim({
        "merkle_root_before": "aaa", "merkle_root_after": "bbb",
        "tree_written": False,
    })

    assert claim["kind"] != "transition", (
        "an after-root that no write produced must not be rendered as a "
        "transition, whatever the payload says"
    )
    assert claim["kind"] == "projected"


def test_claim_kind_unchanged_when_write_produced_the_same_root():
    from core.root_report import root_claim

    claim = root_claim({
        "merkle_root_before": "aaa", "merkle_root_after": "aaa",
        "tree_written": True,
    })

    assert claim["kind"] == "unchanged"


def test_claim_is_unknown_rather_than_guessing():
    """A payload with no roots must not fall through to a rendered state."""
    from core.root_report import root_claim

    assert root_claim({})["kind"] == "unknown"
    assert root_claim({"merkle_root_before": "aaa"})["kind"] == "unknown"


def test_every_claim_kind_is_declared():
    """Guard on the vocabulary itself, so a new kind cannot render unstyled."""
    from core.root_report import CLAIM_KINDS, root_claim

    seen = {
        root_claim({})["kind"],
        root_claim({"merkle_root_before": "a", "merkle_root_projected": "b",
                    "tree_written": False})["kind"],
        root_claim({"merkle_root_before": "a", "merkle_root_after": "b",
                    "tree_written": True})["kind"],
        root_claim({"merkle_root_before": "a", "merkle_root_after": "a",
                    "tree_written": True})["kind"],
    }
    assert seen <= set(CLAIM_KINDS)
    assert seen == set(CLAIM_KINDS), (
        "CLAIM_KINDS declares a kind no input produces, or vice versa"
    )


# ── 4. the consumer end: the route must hand down a verdict, not a raw pair ──
#
# The dashboard inferred a transition from `before !== after`. Moving the
# decision server-side removes the inference rather than asking the client to
# be careful with it.


def _api_payload(tmp_path, monkeypatch, run_payload):
    """Point the server's DEMO_DIR at a temp dir holding a run artifact."""
    sys.path.insert(0, os.path.join(_ROOT, "demo"))
    import demo.server as server

    (tmp_path / "adversarial_validation_run.json").write_text(
        json.dumps(run_payload), encoding="utf-8")
    monkeypatch.setattr(server, "DEMO_DIR", str(tmp_path))

    client = server.app.test_client()
    return client.get("/api/external-validation").get_json()


def test_route_refuses_to_hand_down_a_transition_for_an_unwritten_tree(
        tmp_path, monkeypatch):
    """Roc's exact artifact: an after-root beside tree_written false."""
    data = _api_payload(tmp_path, monkeypatch, {
        "counters": [],
        "merkle_root_before": "07dd20bb",
        "merkle_root_after": "e51c1c16",
        "tree_written": False,
    })

    assert data["root_claim"]["kind"] == "projected", (
        "the route passed a bare root pair through and the dashboard rendered "
        "MERKLE ROOT TRANSITION for a tree whose bytes never changed"
    )


def test_route_reports_a_projection_from_the_current_field_name(
        tmp_path, monkeypatch):
    data = _api_payload(tmp_path, monkeypatch, {
        "counters": [],
        "merkle_root_before": "07dd20bb",
        "merkle_root_projected": "47c5777d",
        "tree_written": False,
    })

    claim = data["root_claim"]
    assert claim["kind"] == "projected"
    assert claim["projected"] == "47c5777d"


def test_route_allows_a_real_transition(tmp_path, monkeypatch):
    """The fix must not be bought by making a transition unreportable."""
    data = _api_payload(tmp_path, monkeypatch, {
        "counters": [],
        "merkle_root_before": "07dd20bb",
        "merkle_root_after": "e51c1c16",
        "tree_written": True,
    })

    assert data["root_claim"]["kind"] == "transition"


def test_run_validation_producer_cannot_emit_an_unobserved_after_root():
    """The SECOND producer. /api/run-validation writes the artifact that
    /api/external-validation reads FIRST, and it computed an after-root from
    load_tree() without writing the tree either. Fixing only the validator
    would leave the same false transition reachable by another door."""
    import inspect

    import demo.server as server

    src = inspect.getsource(server.api_run_validation)
    assert "build_root_report" in src, (
        "run-validation must emit root fields through the same shape as the "
        "validator, or the defect survives in the other producer"
    )
    assert '"merkle_root_after"' not in src, (
        "an after-root assigned directly is the defect: it names an "
        "observation this route never makes"
    )
