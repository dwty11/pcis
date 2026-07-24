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


def _ensure_note_in_window():
    """Stamp the committed verification note to a today-dated memory file so
    load_recent_memory(days=5) loads it whenever the demo runs. Without this the note (dated
    2026-07-17) falls outside the 5-day window and --live silently runs the ABLATION (no-note)
    condition while presenting itself as the WITH-note demo. Runtime-relative date, fixture-
    sourced content — writes a gitignored working artifact under fixtures/base/memory/."""
    base = os.environ.get("PCIS_BASE_DIR", "")
    memdir = os.path.join(base, "memory")
    if not base or not os.path.isdir(memdir):
        return
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for fn in sorted(os.listdir(memdir)):
        if not fn.endswith(".md") or fn == f"{today}.md":
            continue
        try:
            txt = open(os.path.join(memdir, fn), encoding="utf-8").read().lower()
        except OSError:
            continue
        if "no such" in txt or "reference-system" in txt or "reference system" in txt:
            import shutil
            shutil.copyfile(os.path.join(memdir, fn), os.path.join(memdir, f"{today}.md"))
            return


def _clear_today_stamp():
    """Remove any today-dated memory stamp so the ablation run reads BLANK memory. Only ever
    deletes the generated <today>.md artifact — never the committed dated verification note."""
    base = os.environ.get("PCIS_BASE_DIR", "")
    memdir = os.path.join(base, "memory")
    if not base or not os.path.isdir(memdir):
        return
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    p = os.path.join(memdir, f"{today}.md")
    if os.path.exists(p):
        os.remove(p)


def _model_digest(model):
    """The ollama digest for `model`, or '' if unreachable. A fixture records which model
    SNAPSHOT produced its numbers — a tag like 'qwen3.5:9b' drifts across re-pulls, the digest
    doesn't, so a skeptic can tell whether a live re-run is even the same weights."""
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as r:
            data = json.load(r)
        for m in data.get("models", []):
            if m.get("name") == model:
                return m.get("digest", "")
    except Exception:
        return ""
    return ""


def build_prompt(with_note=True):
    """Assemble the EXACT prompt core/gardener.py main() sends — no hint, no leaf id. with_note
    stamps the verification note into the 5-day window (the shipped demo + --live condition);
    with_note=False clears any stamp so the gardener reads blank memory (the ablation)."""
    if with_note:
        _ensure_note_in_window()   # so --live runs WITH the note in-window, not a silent ablation
    else:
        _clear_today_stamp()       # ablation: the gardener sees no verification evidence
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
    """Extract COUNTER lines as [{branch, content, confidence, target_leaf_id}].

    Delegates to the shipped gardener parser (gardener.parse_gardener_output) so the demo
    shows EXACTLY what the real gardener parses — and inherits its robustness that this
    file's old hand-rolled split lacked. That split used ``line.split("|")`` with no bound,
    so a temp-0.7 answer whose content itself contains ``|`` scrambled the fields: a bare
    leaf-id UUID landed in the content slot and confidence became ``None``. The gardener uses
    ``split("|", 4)`` (content may contain pipes), falls back to ``Conf=0.X``/0.65 instead of
    ``None``, and cleans leaf-ids via clean_leaf_id — so counters render as argument text +
    a real confidence, not "conf None" gibberish.
    """
    counters, _synapses, _flags = g.parse_gardener_output(raw)
    return [{"branch": c["branch"], "content": c["content"], "confidence": c["confidence"],
             "target_leaf_id": c.get("original_leaf_id")} for c in counters]


def _hits_plant(target, plant):
    """Prefix-tolerant plant match — same rule replay.py renders with. A recovered id may be a
    short form while the tree stores the full UUID, so exact == would undercount vs a raw scan."""
    if not target or not plant:
        return False
    t, p = str(target).strip().lower(), str(plant).strip().lower()
    return t == p or (len(t) >= 8 and (p.startswith(t) or t.startswith(p)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--passes", type=int, default=10)
    ap.add_argument("--out", default=os.path.join(HERE, "fixtures"))
    ap.add_argument("--no-note", action="store_true",
                    help="record the ABLATION condition (blank memory) into no_note_hit_rate.json")
    args = ap.parse_args()

    with_note = not args.no_note
    plant = open(os.path.join(HERE, "fixtures", "PLANT_ID.txt"), encoding="utf-8").read().strip()
    prompt = build_prompt(with_note=with_note)
    model = g.GARDENER_MODEL
    digest = _model_digest(model)

    runs = []
    canonical = None
    for i in range(args.passes):
        raw = g.call_ollama(prompt)
        counters = parse_counters(raw)
        hit = any(_hits_plant(c["target_leaf_id"], plant) for c in counters)
        plant_counter = next((c for c in counters if _hits_plant(c["target_leaf_id"], plant)), None)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        runs.append({"pass": i + 1, "timestamp": stamp, "n_counters": len(counters),
                     "hit_plant": hit,
                     "plant_counter": plant_counter,
                     "targets": [(c["target_leaf_id"] or "")[:8] for c in counters]})
        print(f"pass {i+1}/{args.passes}: {len(counters)} counters, plant_hit={hit}")
        # canonical = the first real run that lands a counter on the plant (with-note run only)
        if with_note and canonical is None and hit:
            canonical = {
                "model": model,
                "model_digest": digest,
                "timestamp": stamp,
                "prompt": prompt,
                "raw_response": raw,
                "counters": counters,
                "plant_id": plant,
            }

    hits = sum(1 for r in runs if r["hit_plant"])
    os.makedirs(args.out, exist_ok=True)
    rate_file = "hit_rate.json" if with_note else "no_note_hit_rate.json"
    if with_note and canonical is not None:
        with open(os.path.join(args.out, "canonical_run.json"), "w", encoding="utf-8") as f:
            json.dump(canonical, f, indent=2, ensure_ascii=False)
    with open(os.path.join(args.out, rate_file), "w", encoding="utf-8") as f:
        json.dump({"model": model, "model_digest": digest,
                   "condition": "with_note" if with_note else "no_note",
                   "passes": args.passes, "plant_hits": hits,
                   "runs": runs}, f, indent=2, ensure_ascii=False)
    print(f"\nHIT-RATE: {hits}/{args.passes} passes landed a counter on the plant "
          f"(model {model} @ {digest[:12]}, {'with' if with_note else 'NO'} note).")
    print(f"{rate_file}:", "written")
    if with_note:
        print("canonical_run.json:", "written" if canonical else "NOT written (no hit in any pass)")


if __name__ == "__main__":
    main()
