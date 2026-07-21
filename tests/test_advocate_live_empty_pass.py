"""The demo must never fabricate a challenge that didn't happen.

On a live pass where the gardener returns no counter on the plant (this model comes
back empty ~40% of the time), beat_verdict must inject NO counter leaf, create NO
synapse, and render NO confidence move — and say so plainly. The bug this guards:
--replay always carries the recorded counter, so the fabrication was invisible until
--live was executed for the first time (2026-07-21) and hit an empty pass, where the
demo claimed the claim "MOVED under challenge" with an empty "COUNTER:". That is the
exact failure mode PCIS exists to catch.
"""
import os
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TESTS)
sys.path.insert(0, os.path.join(REPO, "core"))
sys.path.insert(0, os.path.join(REPO, "demo", "advocate-demo"))
import replay  # noqa: E402


def _leaf_count(tree):
    return sum(len(b["leaves"]) for b in tree["branches"].values())


def _has_counter_leaf(tree):
    return any(lf["content"].startswith("COUNTER:")
               for b in tree["branches"].values() for lf in b["leaves"])


def test_empty_pass_injects_no_counter_and_renders_no_move(capsys):
    tree = replay._load("seed_tree.json")
    plant_id = replay._plant_id()
    before = _leaf_count(tree)
    tree_after, synapses, cid = replay.beat_verdict(tree, {"counters": []}, plant_id)
    out = capsys.readouterr().out
    # No fabricated counter, ever.
    assert _leaf_count(tree_after) == before, "empty pass must not add a leaf"
    assert not _has_counter_leaf(tree_after), "empty pass must not inject a COUNTER leaf"
    assert cid is None
    assert synapses == {"synapses": []}, "empty pass must create no CONTRADICTS synapse"
    # No verdict move rendered.
    assert "MOVED under challenge" not in out
    assert "net-under-challenge" not in out
    # Say so plainly, and point at the locked run.
    assert "--replay" in out


def test_real_counter_on_the_plant_still_renders_the_move(capsys):
    tree = replay._load("seed_tree.json")
    plant_id = replay._plant_id()
    canonical = {"counters": [{"target_leaf_id": plant_id, "branch": "precedent",
                               "content": "Meridian v. Calloway does not exist",
                               "confidence": 0.65}]}
    tree_after, synapses, cid = replay.beat_verdict(tree, canonical, plant_id)
    out = capsys.readouterr().out
    assert cid is not None
    assert _has_counter_leaf(tree_after)
    assert synapses["synapses"][0]["relation"] == "CONTRADICTS"
    assert "MOVED under challenge" in out
