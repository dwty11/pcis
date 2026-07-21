#!/usr/bin/env python3
"""
replay.py — the Advocate Demo, sixty seconds, terminal-first.

Default: replays a locked, recorded REAL gardener run (fixtures/canonical_run.json)
with full provenance on screen. `--live` runs the shipped gardener fresh against the
same seeded tree on your own local model.

What this demo honestly claims (load-bearing — do not soften):
  An unsupported, high-confidence claim was challenged against the record's OWN
  verification note. Its confidence MOVED under challenge and the challenge is now
  on the record, surfaced for human review. PCIS did not prove the ruling doesn't
  exist, and the claim did not "fail" — it moved, and the record grew. The court
  says verification is the professional's duty; the demo makes that duty structural.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
FIX = os.path.join(HERE, "fixtures")
sys.path.insert(0, os.path.join(REPO, "core"))
sys.path.insert(0, HERE)

# Windows (and piped) stdout can default to a non-UTF-8 codec that cannot encode this
# demo's box-drawing / non-ASCII. Force UTF-8 so it renders everywhere (no-op if already).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

import knowledge_tree as kt
import verdict as V

RULE = "─" * 64


def _load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


def _plant_id():
    with open(os.path.join(FIX, "PLANT_ID.txt"), encoding="utf-8") as f:
        return f.read().strip()


def _find(tree, lid):
    for bn, b in tree.get("branches", {}).items():
        for lf in b["leaves"]:
            if lf["id"] == lid:
                return bn, lf
    return None, None


def _avg_conf(tree):
    cs = [lf["confidence"] for b in tree["branches"].values() for lf in b["leaves"]]
    return sum(cs) / len(cs) if cs else 0.0


def beat_tree(tree, plant_id):
    n = sum(len(b["leaves"]) for b in tree["branches"].values())
    print(RULE)
    print(f"  LEGAL-ASSISTANT AGENT · {n} claims · avg confidence {_avg_conf(tree):.2f}")
    print(RULE)
    # three sample leaves in tree order: two ordinary + the plant, NOT highlighted
    pb, plant = _find(tree, plant_id)
    samples = []
    for lf in tree["branches"]["precedent"]["leaves"][:3]:
        samples.append(("precedent", lf))
    for _b, lf in samples:
        print(f"  [{lf['id'][:8]}] precedent  conf {lf['confidence']:.2f}  "
              f"src={lf['source']:<8} {lf['content'][:74]}")
    print()
    print("  SEEDED SCENARIO — synthetic case file; one claim is deliberately")
    print("  unsupported. The gardener has NOT been told which one.")


def beat_context():
    with open(os.path.join(FIX, "base", "memory", "2026-07-17.md"), encoding="utf-8") as f:
        note = f.read()
    print("\n" + RULE)
    print("  RECENT SESSION MEMORY (last 5 days) — the context the gardener reads:")
    print(RULE)
    for line in note.strip().splitlines():
        print("  " + line)


def beat_attack(canonical, plant_id, live=False):
    print("\n" + RULE)
    if live:
        print("  LIVE gardener pass — your local model, fresh run:")
    else:
        print(f"  REPLAY of a recorded run (model: {canonical['model']}, "
              f"{canonical['timestamp']}) — run --live for a fresh one.")
    print(RULE)
    counters = canonical["counters"]
    for c in counters:
        tag = "[on the plant]" if c["target_leaf_id"] == plant_id else "[routine]     "
        print(f"  ⚔️  {tag}  {c['branch']} counter, conf {c['confidence']}")
        print(f"        {c['content'][:78]}")
    print()
    if counters:
        print("  The gardener always attacks — that's its job. Note it challenged")
        print("  several leaves (some weakly). What matters is which one BITES —")
        print("  and you see all of them, on the record.")
    else:
        print("  No counters this pass — this model returns nothing on some runs.")


def beat_ablation():
    """The moat: one recorded hit could be luck. The RATE — and its dependence on
    the verification note — is what proves the untold gardener FOUND the plant."""
    with open(os.path.join(FIX, "hit_rate.json"), encoding="utf-8") as f:
        withn = json.load(f)
    with open(os.path.join(FIX, "no_note_hit_rate.json"), encoding="utf-8") as f:
        without = json.load(f)
    print("\n" + RULE)
    print("  WAS THAT LUCK? — the untold gardener, measured across repeated passes")
    print(RULE)
    print(f"    WITH the verification note in memory        "
          f"{withn['plant_hits']}/{withn['passes']} passes landed a counter on the plant")
    print(f"    WITHOUT the note (same tree, same plant)    "
          f"{without['plant_hits']}/{without['passes']} passes")
    print()
    print("  The note is load-bearing: the gardener finds the fabrication when the")
    print("  record carries the evidence, and misses it when the memory is blank.")
    print("  Not a scripted highlight — a measured rate. Bounded: one model")
    print(f"  ({withn['model']}), one tree, one plant — an illustration, not a benchmark.")


def beat_verdict(tree, canonical, plant_id):
    """Render the money shot ONLY from a genuine counter on the plant. If this pass
    produced none, say so — never inject a counter to manufacture a move."""
    pc = next((c for c in canonical["counters"] if c["target_leaf_id"] == plant_id), None)
    if pc is None:
        print("\n" + RULE)
        print("  NO VERDICT THIS PASS — the gardener raised no counter on the plant.")
        print(RULE)
        print("  Nothing is injected: no counter leaf, no synapse, no confidence move —")
        print("  a challenge that didn't happen is not put on the record. This model")
        print("  returns nothing on roughly 4 of 10 passes, which is why the ablation is")
        print("  6/10 and why the demo ships a recording. Use --replay for the locked")
        print("  hit, or re-run --live.")
        return tree, {"synapses": []}, None
    # apply the plant's real counter → CONTRADICTS synapse, then render from assess_belief
    ctr_id = kt.add_knowledge(tree, "precedent", "COUNTER: " + pc["content"],
                              source="gardener", confidence=pc["confidence"])
    ctr_id = ctr_id if isinstance(ctr_id, str) else ctr_id["id"]
    synapses = {"synapses": [{"from_leaf": ctr_id, "to_leaf": plant_id,
                              "relation": "CONTRADICTS", "note": "Gardener counter-challenge"}]}
    print("\n" + V.render(tree, synapses, plant_id))
    return tree, synapses, ctr_id


def beat_record(tree_before, tree_after):
    r0 = kt.compute_root_hash(tree_before)
    r1 = kt.compute_root_hash(tree_after)
    print("\n" + RULE)
    print(f"  root: {r0[:8]}…  →  {r1[:8]}…")
    print("  The record didn't change. It GREW — the counter is now part of it,")
    print("  and the Merkle root moved to prove it. Nothing was silently rewritten.")
    print(RULE)


def beat_close(landed=True):
    print("\n" + RULE)
    print("  Verification is the professional's duty. PCIS makes it STRUCTURAL.")
    print()
    if landed:
        print("  The claim was not proven false, and it did not fail — its confidence")
        print("  moved under challenge and the challenge is on the record for review.")
    else:
        print("  Nothing moved this pass and nothing was recorded — the gardener raised")
        print("  no counter. --replay shows the locked run where it lands.")
    print()
    print("  Run it against your own local model:  ./run_demo.sh --live")
    print("  Everything runs on your machine. Nothing leaves it.")
    print(RULE)


def run(live=False):
    tree = _load("seed_tree.json")
    plant_id = _plant_id()
    tree_before = json.loads(json.dumps(tree))  # deep copy for the root-before

    if live:
        canonical = _live_run(plant_id)
    else:
        cpath = os.path.join(FIX, "canonical_run.json")
        if not os.path.exists(cpath):
            print("No canonical_run.json — run record_canonical.py first "
                  "(or use --live).", file=sys.stderr)
            return 1
        canonical = _load("canonical_run.json")

    beat_tree(tree, plant_id)
    beat_context()
    beat_attack(canonical, plant_id, live=live)
    beat_ablation()
    tree_after, _syn, cid = beat_verdict(tree, canonical, plant_id)
    if cid is not None:
        beat_record(tree_before, tree_after)
    beat_close(landed=cid is not None)
    return 0


def _live_run(plant_id):
    """Run the shipped gardener fresh and shape its output like a canonical run."""
    sys.path.insert(0, REPO)
    import gardener as g
    from record_canonical import build_prompt, parse_counters
    from datetime import datetime, timezone
    raw = g.call_ollama(build_prompt())
    counters = parse_counters(raw)
    return {"model": g.GARDENER_MODEL,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "prompt": "(live)", "raw_response": raw, "counters": counters,
            "plant_id": plant_id}


if __name__ == "__main__":
    sys.exit(run(live="--live" in sys.argv))
