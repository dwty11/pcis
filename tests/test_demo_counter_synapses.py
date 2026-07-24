"""Demo integrity: every COUNTER leaf in the demo tree must carry a matching
CONTRADICTS synapse to its bracketed target.

Regression guard for the belief/adversarial split a cold read of the dashboard
surfaced: seed_demo_counters.py planted COUNTER leaves but zero synapses, and
demo_synapses.json was hand-authored with only (invalid) REINFORCES edges. The
ADVERSARIAL panel reads COUNTER content and showed the challenge; the BELIEF
panel is synapse-driven and reported contradictions:0 for the same leaf. The two
panels disagreed because they read two unconnected data sources with no bridge.

The generator now mirrors core/gardener.py:1180 — every committed counter gets a
CONTRADICTS synapse (from=counter leaf, to=challenged leaf). These tests fail the
build the moment a COUNTER leaf ships without its synapse, so the split can't
recur invisibly.
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.belief_traversal import assess_belief
from core.knowledge_synapses import VALID_RELATIONS

DEMO = REPO / "demo"
TREE = json.loads((DEMO / "demo_tree.json").read_text(encoding="utf-8"))
SYNAPSES = json.loads((DEMO / "demo_synapses.json").read_text(encoding="utf-8"))

_BRACKET = re.compile(r"COUNTER:\s*\[([a-f0-9]+)\]")


def _counter_leaves():
    """(counter_leaf_id, challenged_target_id) for every COUNTER: leaf."""
    out = []
    for branch in TREE["branches"].values():
        for leaf in branch["leaves"]:
            if leaf["content"].startswith("COUNTER:"):
                m = _BRACKET.match(leaf["content"])
                out.append((leaf["id"], m.group(1) if m else None))
    return out


def test_demo_has_counter_leaves():
    # Guard the guards: if the demo ever ships zero counters, the checks below
    # would pass vacuously. Fail loudly instead.
    assert _counter_leaves(), "demo_tree.json has no COUNTER leaves to check"


def test_every_counter_leaf_has_contradicts_synapse():
    contradicts = {
        (s["from_leaf"], s["to_leaf"])
        for s in SYNAPSES["synapses"]
        if s["relation"] == "CONTRADICTS"
    }
    missing = []
    for counter_id, target_id in _counter_leaves():
        assert target_id, f"counter {counter_id} has no [target] bracket in its content"
        if (counter_id, target_id) not in contradicts:
            missing.append((counter_id, target_id))
    assert not missing, (
        f"{len(missing)} COUNTER leaf(ves) have no CONTRADICTS synapse to their target "
        f"(the belief panel is blind to them): {missing}"
    )


def test_assess_belief_sees_contradiction_on_challenged_leaf():
    # 01f3a4ac52bf = "HIGH RISK: Prompt injection ..." (base conf 0.92), challenged
    # by counter 8817f6ae7dbc. With its CONTRADICTS synapse present, the belief
    # engine must register a contradiction and pull net confidence below base.
    target = "01f3a4ac52bf"
    a = assess_belief(target, tree=TREE, synapses=SYNAPSES)
    assert a["contradiction_count"] > 0, (
        "assess_belief reports no contradiction on a leaf the adversarial panel shows a "
        "counter for — the belief and adversarial panels disagree."
    )
    assert a["net_confidence"] < a["base_confidence"], (
        "a registered contradiction must move net confidence below the authored base."
    )


def test_demo_synapses_use_only_valid_relations():
    bad = sorted({
        s["relation"] for s in SYNAPSES["synapses"]
        if s["relation"] not in VALID_RELATIONS
    })
    assert not bad, (
        f"demo_synapses.json carries relation(s) absent from VALID_RELATIONS "
        f"{sorted(VALID_RELATIONS)}: {bad} — every layer silently ignores them."
    )
