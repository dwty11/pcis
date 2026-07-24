"""The Advocate Demo must render the ablation on screen — and the ablation's FINDING is the
counter text, not the rate.

The gardener targets the 0.95 outlier with or without the verification note (7/10 vs 6/10 —
about the same); it attacks the lone high-confidence model-sourced claim on priors either way.
What the note changes is what the challenge SAYS: a generic doctrinal hedge without the recorded
evidence, the specific "resolves to no decision — fabricated" finding with it. These assert both
the substance contrast and the two (close) rates reach the viewer, sourced from the recorded
fixtures, stated with their bound + pinned digest + the live-rates-vary disclosure so the demo
cannot overclaim.
"""
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADV = os.path.join(REPO, "demo", "advocate-demo")


def _fixture_rates():
    with open(os.path.join(ADV, "fixtures", "hit_rate.json"), encoding="utf-8") as f:
        withn = json.load(f)
    with open(os.path.join(ADV, "fixtures", "no_note_hit_rate.json"), encoding="utf-8") as f:
        without = json.load(f)
    return withn, without


def _replay_output():
    r = subprocess.run(
        [sys.executable, os.path.join(ADV, "replay.py")],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_ablation_fixtures_are_the_recorded_numbers():
    """Guards the recorded numbers: 7/10 with the note, 6/10 without — close, by design."""
    withn, without = _fixture_rates()
    assert (withn["plant_hits"], withn["passes"]) == (7, 10)
    assert (without["plant_hits"], without["passes"]) == (6, 10)


def test_replay_renders_the_ablation_rate_on_screen():
    withn, without = _fixture_rates()
    out = _replay_output()
    with_rate = f"{withn['plant_hits']}/{withn['passes']}"        # 7/10
    without_rate = f"{without['plant_hits']}/{without['passes']}"  # 6/10
    assert with_rate in out, f"with-note rate {with_rate} is not on screen"
    assert without_rate in out, f"without-note rate {without_rate} is not on screen"


def test_replay_renders_the_substance_contrast():
    """The finding is the counter TEXT: without the note a generic hedge, with it the specific
    'fabricated / no such decision' finding. Both framings and the recorded finding text must
    reach the viewer — that contrast, not the close 7-vs-6 rates, is what the ablation proves."""
    out = _replay_output().lower()
    assert "generic doctrinal hedge" in out, "the without-note challenge isn't framed as a hedge"
    assert "verified finding" in out, "the with-note challenge isn't framed as the finding"
    assert any(m in out for m in ("fabricated", "no such", "no decision", "no results",
                                  "non-existent")), (
        "the recorded specific-finding text (fabricated / no such decision) isn't on screen")


def test_replay_states_the_ablation_bound_so_it_cannot_overclaim():
    """The rate must ship with its scope — one model, one tree, one plant — plus the pinned
    model digest and the live-rates-vary disclosure."""
    out = _replay_output().lower()
    assert "one model" in out and "one tree" in out and "one plant" in out, (
        "ablation rate rendered without its bound — reads as a benchmark it isn't")
    assert "vary" in out, "missing the live-rates-vary disclosure"
    assert "6488c96" in out, "missing the pinned model digest"
