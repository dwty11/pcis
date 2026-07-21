#!/usr/bin/env python3
"""
verdict.py — render the Advocate Demo's money shot from what the code computes.

Given the seeded tree, the synapses (incl. the gardener's committed CONTRADICTS
counter), and the plant leaf id, this prints the BEFORE/AFTER belief state using
the repo's own `belief_traversal.assess_belief`. It states exactly what the shipped
math produces — base confidence, net-under-challenge, the mechanism, the stance,
and that the challenge is surfaced for review.

The honesty line is load-bearing (ruled 2026-07-20): the claim MOVED under challenge
and was SURFACED for review. It did not fail, it did not flip, it is not CONTESTED —
a single counter moves a 0.95 claim into the mid-0.80s (the exact net varies with the
counter's own confidence and is rendered from the live computation, not pinned here;
CONTRADICTION_WEIGHT 0.15) and it stays CONFIDENT. The demo prints what the code computes.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "core"))

import belief_traversal as bt  # the shipped stance engine


def _counter_of(plant_id, synapses, tree):
    """Return (counter_leaf, note) for the first CONTRADICTS synapse targeting the
    plant, or (None, None)."""
    for s in synapses.get("synapses", []):
        if s.get("relation") == "CONTRADICTS" and s.get("to_leaf") == plant_id:
            cid = s.get("from_leaf")
            for b in tree.get("branches", {}).values():
                for lf in b.get("leaves", []):
                    if lf["id"] == cid:
                        return lf, s.get("note", "")
    return None, None


def render(tree, synapses, plant_id, plant_branch="precedent"):
    """Return the money-shot screen as a string. Numbers come straight from
    assess_belief — no hardcoding."""
    before = bt.assess_belief(plant_id, tree=tree, synapses={"synapses": []})
    after = bt.assess_belief(plant_id, tree=tree, synapses=synapses)
    counter, _note = _counter_of(plant_id, synapses, tree)
    counter_text = (counter["content"] if counter else
                    "COUNTER: claimed ruling not found in reference-system check")

    short = plant_id[:8]
    L = []
    L.append("  ── VERDICT " + "─" * 52)
    L.append(f"  BEFORE  {plant_branch}/{short}   base confidence "
             f"{before['base_confidence']:.2f}   {before['stance']}")
    L.append("")
    L.append("  gardener counter attached  ──[CONTRADICTS]──>  precedent/{}".format(short))
    L.append(f'      "{_wrap(counter_text, 66)}"')
    L.append("")
    L.append(f"  AFTER   {plant_branch}/{short}   base {after['base_confidence']:.2f} · "
             f"net-under-challenge {after['net_confidence']:.2f}   {after['stance']}")
    L.append("")
    L.append(f"  The claim MOVED under challenge ({before['base_confidence']:.2f} -> "
             f"net {after['net_confidence']:.2f}, CONTRADICTION_WEIGHT "
             f"{bt.CONTRADICTION_WEIGHT}) and the counter is now on the record,")
    L.append(f"  surfaced for human review. It did not fail and it did not flip — "
             f"stance is {after['stance']}.")
    L.append("  " + "─" * 62)
    return "\n".join(L)


def _wrap(text, width):
    """Single-line clip with ellipsis (screen stays one line per counter)."""
    text = " ".join(text.split())
    return text if len(text) <= width else text[:width - 1] + "…"


def verdict_data(tree, synapses, plant_id):
    """Machine-readable form (for the recorder / CI / tests)."""
    before = bt.assess_belief(plant_id, tree=tree, synapses={"synapses": []})
    after = bt.assess_belief(plant_id, tree=tree, synapses=synapses)
    return {
        "plant_id": plant_id,
        "base_before": before["base_confidence"],
        "stance_before": before["stance"],
        "base_after": after["base_confidence"],
        "net_after": after["net_confidence"],
        "stance_after": after["stance"],
        "contradiction_weight": bt.CONTRADICTION_WEIGHT,
    }
