"""test_validator_provenance.py — a counter leaf must record how it was produced.

2026-07-27. The weekly adversarial cron reported "5 COUNTER leaves committed"
and a Merkle root transition. Neither happened. Three silent steps stacked, each
writing the next one's input down as normal:

  1. ``config.json`` named provider ``openrouter``, which is not a key in
     PROVIDER_DEFAULTS, so ``get_provider_config`` **demoted it to ollama** and
     logged a warning nothing reads.
  2. Ollama then 404'd on ``minimax/minimax-m2.7``, a model it does not serve —
     every one of the five calls failed, each falling back to a pre-stored
     paragraph from ``FALLBACK_CHALLENGES``.
  3. The run file recorded the **demoted** provider, and each leaf carried
     ``source="adversarial-<date>"`` with ``confidence=0.65`` — byte-identical
     to what a real challenge produces.

Four of the five "challenges" were the *same* canned paragraph, because
``get_fallback_challenge`` defaults to the ``compliance`` text for any branch
not in its key set.

Then two independent readers each opened that run file and repeated its claim
back as established fact. Neither was careless; the artifact simply described
what it set out to do, and nothing downstream could tell that apart from what
occurred. That is the argument for recording outcomes rather than intentions —
a reader cannot be expected to out-argue a file that states a result.

THE RULE THESE TESTS ENCODE
===========================
A COUNTER leaf without a real challenge is a templated response, not an
adversarial pass. It does not get committed. What did happen gets recorded.
"""

from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, _ROOT)


def _leaf(leaf_id, content="a claim worth challenging", confidence=0.9):
    return {"id": leaf_id, "content": content, "confidence": confidence}


def _selected(*ids):
    """Shape returned by select_leaves: (branch_name, leaf) pairs."""
    return [("compliance", _leaf(i)) for i in ids]


# ── 1. the upstream cause: an unsupported provider must not be substituted ──


def test_unknown_provider_raises_rather_than_demoting():
    """The defect that started it. 'openrouter' is not in PROVIDER_DEFAULTS."""
    from core.adversarial_validator import UnknownProviderError, get_provider_config

    with pytest.raises(UnknownProviderError) as excinfo:
        get_provider_config({"llm_provider": "openrouter",
                             "llm_model": "minimax/minimax-m2.7"})

    assert "openrouter" in str(excinfo.value), (
        "the error must name the provider that was asked for, so the reader "
        "does not have to guess which key was wrong"
    )


def test_supported_provider_still_resolves():
    """The fix must not be bought by refusing everything."""
    from core.adversarial_validator import get_provider_config

    provider, model, url, _key = get_provider_config(
        {"llm_provider": "ollama", "llm_model": "qwen3:14b"}
    )

    assert provider == "ollama"
    assert model == "qwen3:14b"
    assert url


# ── 2. the ruling: no real challenge ⇒ no leaf ──


def test_failed_call_produces_no_counter_leaf():
    from core.adversarial_validator import challenge_leaves

    def always_fails(content, confidence):
        raise RuntimeError("HTTP 404: model not found")

    counters, _attempts = challenge_leaves(
        _selected("aaa", "bbb"), always_fails, model="m"
    )

    assert counters == [], (
        "a COUNTER leaf built from a pre-stored paragraph is a templated "
        "response, not an adversarial challenge — it must not be committed"
    )


def test_failed_call_is_still_recorded_as_an_attempt():
    """Refusing to commit must not also erase the evidence."""
    from core.adversarial_validator import challenge_leaves

    def always_fails(content, confidence):
        raise RuntimeError("HTTP 404: model not found")

    _counters, attempts = challenge_leaves(
        _selected("aaa"), always_fails, model="m"
    )

    assert len(attempts) == 1
    assert attempts[0]["leaf_id"] == "aaa"
    assert attempts[0]["outcome"] == "failed"
    assert "404" in attempts[0]["error"], (
        "the recorded attempt must carry why it failed, or the next reader "
        "cannot tell a dead endpoint from an empty response"
    )


# ── 3. the case J flagged: a mixed run must not read as a clean one ──


def test_mixed_run_is_distinguishable_from_a_clean_run():
    from core.adversarial_validator import challenge_leaves

    def fails_on_second(content, confidence):
        if "bbb" in content:
            raise RuntimeError("HTTP 404")
        return "a genuine counter-argument"

    mixed_counters, mixed_attempts = challenge_leaves(
        [("compliance", _leaf("aaa", "claim aaa")),
         ("compliance", _leaf("bbb", "claim bbb"))],
        fails_on_second, model="m",
    )
    clean_counters, clean_attempts = challenge_leaves(
        [("compliance", _leaf("aaa", "claim aaa")),
         ("compliance", _leaf("ccc", "claim ccc"))],
        lambda c, k: "a genuine counter-argument", model="m",
    )

    assert len(clean_counters) == 2 and len(mixed_counters) == 1

    mixed_outcomes = {a["outcome"] for a in mixed_attempts}
    clean_outcomes = {a["outcome"] for a in clean_attempts}
    assert mixed_outcomes != clean_outcomes, (
        "a run where one of two calls failed must not present the same "
        "outcome set as a run where both answered"
    )


def test_every_outcome_is_in_the_declared_vocabulary():
    """Imports ATTEMPT_OUTCOMES rather than hardcoding a copy of it.

    A test holding its own copy of a producer's status list stays green when
    the producer grows a state the test has never heard of. Asserting against
    the constant means a new outcome shows up here instead of slipping past.
    """
    from core.adversarial_validator import ATTEMPT_OUTCOMES, challenge_leaves

    def fails_on_second(content, confidence):
        if "bbb" in content:
            raise RuntimeError("HTTP 404")
        return "a genuine counter-argument"

    _counters, attempts = challenge_leaves(
        [("compliance", _leaf("aaa", "claim aaa")),
         ("compliance", _leaf("bbb", "claim bbb"))],
        fails_on_second, model="m",
    )

    assert {a["outcome"] for a in attempts} == set(ATTEMPT_OUTCOMES), (
        "this fixture is built to exercise every declared outcome; if the "
        "vocabulary grew, the fixture needs a case for the new state"
    )


def test_summary_counts_are_derived_from_attempts():
    """A headline derived from the set cannot forget a branch."""
    from core.adversarial_validator import challenge_leaves, summarize_attempts

    def fails_on_second(content, confidence):
        if "bbb" in content:
            raise RuntimeError("HTTP 404")
        return "a genuine counter-argument"

    _counters, attempts = challenge_leaves(
        [("compliance", _leaf("aaa", "claim aaa")),
         ("compliance", _leaf("bbb", "claim bbb"))],
        fails_on_second, model="m",
    )
    summary = summarize_attempts(attempts)

    assert summary["live"] == 1
    assert summary["failed"] == 1
    assert summary["attempted"] == 2


# ── 4. the leaf itself must say how it was produced ──


def test_counter_source_is_derived_from_the_outcome():
    """source was a caption naming the configured provider, not the producer."""
    from core.adversarial_validator import challenge_leaves

    counters, _ = challenge_leaves(
        _selected("aaa"), lambda c, k: "a genuine counter-argument", model="m"
    )

    assert counters[0]["produced_by"] == "live-llm"
    assert "live-llm" in counters[0]["source"], (
        "source must encode how the text was produced — a leaf that cannot be "
        "told apart from a canned one is the defect this fix exists to remove"
    )


def test_counter_records_the_model_that_answered():
    from core.adversarial_validator import challenge_leaves

    counters, _ = challenge_leaves(
        _selected("aaa"), lambda c, k: "a genuine counter-argument",
        model="qwen3:14b",
    )

    assert counters[0]["model"] == "qwen3:14b", (
        "the run file recorded the CONFIGURED model even when nothing answered; "
        "the leaf must carry the model that actually produced its text"
    )


# ── 5. the canned-paragraph surface must be gone, not merely unused ──


def test_no_prestored_challenge_can_reach_a_leaf():
    """FALLBACK_CHALLENGES produced 4 identical 'challenges' in one run."""
    import core.adversarial_validator as av

    assert not hasattr(av, "get_fallback_challenge"), (
        "the fallback-to-leaf path is the mechanism that let canned text be "
        "committed as an adversarial pass; leaving it importable invites its "
        "return"
    )


# ── 6. the entry point — this is what the cron actually ran ──
#
# The unit tests above all passed while main() still called a function that no
# longer existed. The run file is written by main(), so main() is what has to
# be driven.


def _stage_run(tmp_path, monkeypatch, challenge):
    """Point the module at a temp tree + output and stub the transport."""
    import json as _json

    import core.adversarial_validator as av
    import knowledge_tree as kt

    tree = {"branches": {}, "root_hash": ""}
    kt.add_knowledge(tree, "compliance", "claim aaa", source="t", confidence=0.9)
    kt.add_knowledge(tree, "lessons", "claim bbb", source="t", confidence=0.85)

    tree_file = tmp_path / "tree.json"
    out_file = tmp_path / "run.json"
    tree_file.write_text(_json.dumps(tree), encoding="utf-8")

    monkeypatch.setattr(av, "TREE_FILE", str(tree_file))
    monkeypatch.setattr(av, "OUTPUT_FILE", str(out_file))
    monkeypatch.setattr(av, "load_config",
                        lambda: {"llm_provider": "ollama", "llm_model": "qwen3:14b"})
    monkeypatch.setattr(av, "send_to_llm", challenge)

    av.main()
    return _json.loads(out_file.read_text(encoding="utf-8"))


def test_main_commits_nothing_when_every_call_fails(tmp_path, monkeypatch):
    """The 2026-07-27 run, reproduced. It reported 5 committed leaves."""
    def all_fail(provider, url, api_key, model, content, confidence):
        raise RuntimeError("HTTP Error 404: Not Found")

    data = _stage_run(tmp_path, monkeypatch, all_fail)

    assert data["counters"] == []
    assert data["entries_challenged"] == 0
    assert data["summary"]["live"] == 0
    assert data["summary"]["failed"] == data["summary"]["attempted"] > 0
    assert "merkle_root_after" not in data, (
        "nothing was committed, so there is no after-root to name — the field "
        "must be absent rather than present-and-equal"
    )
    assert data["merkle_root_projected"] == data["merkle_root_before"]


def test_main_run_file_shows_which_calls_failed(tmp_path, monkeypatch):
    def fails_on_bbb(provider, url, api_key, model, content, confidence):
        if "bbb" in content:
            raise RuntimeError("HTTP Error 404: Not Found")
        return "a genuine counter-argument"

    data = _stage_run(tmp_path, monkeypatch, fails_on_bbb)

    outcomes = sorted(a["outcome"] for a in data["attempts"])
    assert outcomes == ["failed", "live"], (
        "a run where one of two calls failed must not record the same "
        "outcome set as a run where both answered"
    )
    assert data["summary"] == {"attempted": 2, "live": 1, "failed": 1}
    assert data["counters"][0]["produced_by"] == "live-llm"


def test_main_records_that_the_tree_was_not_written(tmp_path, monkeypatch):
    """merkle_root_after is a projection: demo_tree.json is never written."""
    data = _stage_run(
        tmp_path, monkeypatch,
        lambda p, u, k, m, c, conf: "a genuine counter-argument",
    )

    # tree_written is DERIVED from the file's bytes, not asserted. The literal
    # version of this passed even with a real write injected -- it checked the
    # label and never the fact.
    assert data["tree_written"] is False
    assert "merkle_root_after" not in data, (
        "the projection must not be emitted under a name that asserts an "
        "observation; a consumer renders a transition from before+after"
    )
    assert data["merkle_root_projected"]


def test_main_refuses_an_unsupported_provider(tmp_path, monkeypatch):
    """End to end: the cron's real config must stop, not demote."""
    import core.adversarial_validator as av

    monkeypatch.setattr(av, "load_config",
                        lambda: {"llm_provider": "openrouter",
                                 "llm_model": "minimax/minimax-m2.7"})

    with pytest.raises(av.UnknownProviderError):
        av.main()
