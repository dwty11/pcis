#!/usr/bin/env python3
"""
record_canonical.py — run the REAL, unmodified gardener over the seeded tree N times,
record one real run as the canonical replay, and report the honest hit-rate.

Honesty rules (baked in):
  * The gardener is never told which leaf to attack. This script builds the exact
    shipped GARDENER_PROMPT (same inputs as core/gardener.py main) — no leaf id, no
    hint — and calls the shipped call_ollama. A skeptic can diff the prompt here
    against the gardener's.
  * The canonical run is a REAL run (the first that lands a counter on the plant),
    recorded with full provenance: model, verbatim prompt, timestamp, raw response.
  * The hit-rate is reported as N-of-M from actual passes. No adjective, no rounding
    up — if it hits 4 of 10, it says 4 of 10.

Usage:
  PCIS_BASE_DIR=.../fixtures/base PCIS_TREE_FILE=.../seed_tree.json \
  PCIS_GARDENER_MODEL=qwen3.5:9b python3 record_canonical.py --passes 10
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "core"))
sys.path.insert(0, REPO)

import gardener as g  # the shipped gardener — same module the demo runs


def build_prompt():
    """Assemble the EXACT prompt core/gardener.py main() sends — no hint, no leaf id."""
    tree = g.load_tree()
    tree_text = g.format_tree_for_prompt(tree, focus_branch=None)
    recent_memory = g.load_recent_memory(days=5)
    branch_list = ", ".join(sorted(tree.get("branches", {}).keys()))
    already_challenged_text = "  (none yet — all leaves are fair targets)"
    return g.GARDENER_PROMPT.format(
        tree_text=tree_text,
        recent_memory=recent_memory[:1500],
        already_challenged=already_challenged_text,
        branch_list=branch_list,
        branch_health=g.compute_branch_health(tree),
    )


def parse_counters(raw):
    """Extract COUNTER lines: [{branch, content, confidence, target_leaf_id}].

    Uses the shared gardener.strip_list_marker so a model that wraps its output in a
    numbered/bulleted list (a real behavior — qwen3.5:9b does it on ~3/10 passes) is not
    silently dropped. Kept parser-identical to the gardener otherwise.
    """
    out = []
    for line in raw.splitlines():
        line = g.strip_list_marker(line.strip())
        if not line.startswith("COUNTER|"):
            continue
        parts = line.split("|")
        if len(parts) < 5:
            continue
        target = re.sub(r"[^a-f0-9-]", "", parts[4].strip())
        try:
            conf = float(parts[3].strip())
        except ValueError:
            conf = None
        out.append({"branch": parts[1].strip(), "content": parts[2].strip(),
                    "confidence": conf, "target_leaf_id": target})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--passes", type=int, default=10)
    ap.add_argument("--out", default=os.path.join(HERE, "fixtures"))
    args = ap.parse_args()

    plant = open(os.path.join(HERE, "fixtures", "PLANT_ID.txt"), encoding="utf-8").read().strip()
    prompt = build_prompt()
    model = g.GARDENER_MODEL

    runs = []
    canonical = None
    for i in range(args.passes):
        raw = g.call_ollama(prompt)
        counters = parse_counters(raw)
        hit = any(c["target_leaf_id"] == plant for c in counters)
        plant_counter = next((c for c in counters if c["target_leaf_id"] == plant), None)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        runs.append({"pass": i + 1, "timestamp": stamp, "n_counters": len(counters),
                     "hit_plant": hit,
                     "plant_counter": plant_counter,
                     "targets": [c["target_leaf_id"][:8] for c in counters]})
        print(f"pass {i+1}/{args.passes}: {len(counters)} counters, plant_hit={hit}")
        # canonical = the first real run that lands a counter on the plant
        if canonical is None and hit:
            canonical = {
                "model": model,
                "timestamp": stamp,
                "prompt": prompt,
                "raw_response": raw,
                "counters": counters,
                "plant_id": plant,
            }

    hits = sum(1 for r in runs if r["hit_plant"])
    os.makedirs(args.out, exist_ok=True)
    if canonical is not None:
        with open(os.path.join(args.out, "canonical_run.json"), "w", encoding="utf-8") as f:
            json.dump(canonical, f, indent=2, ensure_ascii=False)
    with open(os.path.join(args.out, "hit_rate.json"), "w", encoding="utf-8") as f:
        json.dump({"model": model, "passes": args.passes, "plant_hits": hits,
                   "runs": runs}, f, indent=2, ensure_ascii=False)
    print(f"\nHIT-RATE: {hits}/{args.passes} passes landed a counter on the plant "
          f"(model {model}).")
    print("canonical_run.json:", "written" if canonical else "NOT written (no hit in any pass)")


if __name__ == "__main__":
    main()
