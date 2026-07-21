"""The Advocate Demo must render the ablation RATE on screen — the moat.

A single counter landing on the plant reads as a scripted nudge. The
6/10-with-note vs 0/5-without-note contrast is what proves the gardener FOUND
the plant (and that the verification note is load-bearing), not that it was
pointed at it. These assert the rate reaches the viewer, sourced from the
recorded fixtures, and stated with its bound so the demo can't overclaim.
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
    """Guards the bound: exactly the numbers J ruled — 6/10 with note, 0/5 without."""
    withn, without = _fixture_rates()
    assert (withn["plant_hits"], withn["passes"]) == (6, 10)
    assert (without["plant_hits"], without["passes"]) == (0, 5)


def test_replay_renders_the_ablation_rate_on_screen():
    withn, without = _fixture_rates()
    out = _replay_output()
    with_rate = f"{withn['plant_hits']}/{withn['passes']}"        # 6/10
    without_rate = f"{without['plant_hits']}/{without['passes']}"  # 0/5
    assert with_rate in out, f"with-note rate {with_rate} is not on screen"
    assert without_rate in out, f"without-note rate {without_rate} is not on screen"


def test_replay_states_the_ablation_bound_so_it_cannot_overclaim():
    """The rate must ship with its scope — one model, one tree, one plant."""
    out = _replay_output().lower()
    assert "one model" in out and "one tree" in out and "one plant" in out, (
        "ablation rate rendered without its bound — reads as a benchmark it isn't")
