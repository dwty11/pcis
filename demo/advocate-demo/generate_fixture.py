#!/usr/bin/env python3
"""
generate_fixture.py — build the Advocate Demo's seeded case file.

Produces a legal-assistant knowledge tree of ~18 ordinary case-file claims plus
ONE plant: a well-formatted, entirely fabricated case citation held at 0.95
confidence with source=model. A human skimming the tree passes it — which is the
documented failure mode (the fined advocate trusted a perfectly-formatted cite).

The contradicting evidence is written where the gardener actually looks: a dated
session note in the base dir's memory/, recording that a reference-system check
found no such case. Nothing here tells the gardener which leaf to attack.

Reproducible-IN-KIND (Fable §3.5): re-running regenerates a same-class tree; the
committed fixtures/ JSON + note are the canonical artifacts the demo replays.

Usage:
  python3 generate_fixture.py [--out fixtures] [--memory-date 2026-07-17]
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "core"))

import knowledge_tree as kt  # the real tree builder — valid ids + hashes


# The plant + its neighbors. Each tuple: (branch, content, source, confidence).
# The plant is index 0: a fabricated case citation, jurisdiction-neutral, formatted
# like the two verified precedents beneath it, held at 0.95 with source=model.
LEAVES = [
    # ── precedent (the plant + two verified holdings) ──
    ("precedent",
     "Under Meridian v. Calloway Holdings (2024), a party's failure to disclose a known "
     "conflict of interest within 14 days waives its right to compel arbitration — directly "
     "supporting our motion to keep the Delgado matter in litigation.",
     "model", 0.95),  # ← THE PLANT (no source verification; contradicted by the 07-17 note)
    ("precedent",
     "A controlling appellate decision holds that arbitration agreements containing "
     "class-action waivers are enforceable; verified against the case-law reference system "
     "on 2026-06-30.",
     "reference-system", 0.90),
    ("precedent",
     "Higher-court precedent holds that the governing arbitration law preempts local rules "
     "that disfavor arbitration; confirmed in the primary case-law database.",
     "reference-system", 0.90),
    # ── deadlines ──
    ("deadlines",
     "Delgado matter: responsive pleading due 2026-08-14 (30 days from service on 2026-07-15 "
     "under the governing procedural rule).", "docket", 0.92),
    ("deadlines",
     "Nunez appeal: opening brief due 2026-09-02 per the appellate court's scheduling order.",
     "court-order", 0.90),
    ("deadlines",
     "Meridian arbitration: discovery cutoff 2026-10-30 per the case-management order.",
     "cmo", 0.88),
    ("deadlines",
     "Expert disclosures due 2026-08-01 (90 days before trial under the governing disclosure "
     "rule).", "rule", 0.85),
    # ── statutes ──
    ("statutes",
     "Under the governing procedural rules, a defendant must serve its answer within 21 days "
     "of service, or 60 days if service is waived.", "rules", 0.95),
    ("statutes",
     "The jurisdictional statute requires an amount in controversy above the statutory "
     "threshold and complete diversity of the parties.", "statute", 0.95),
    ("statutes",
     "Under the governing arbitration statute, written arbitration agreements are valid, "
     "irrevocable, and enforceable save upon grounds that would revoke any contract.",
     "statute", 0.93),
    # ── procedure ──
    ("procedure",
     "Delgado: file the motion to compel litigation before the responsive-pleading deadline "
     "to preserve the argument.", "session", 0.80),
    ("procedure",
     "The court's local rules limit opposition briefs to 25 pages absent leave of court.",
     "local-rule", 0.90),
    ("procedure",
     "Meet-and-confer is required before any discovery motion under the local rules.",
     "local-rule", 0.90),
    ("procedure",
     "Filing is through the court's electronic filing system; deliver a courtesy paper copy "
     "to chambers for any motion over 10 pages.", "standing-order", 0.85),
    # ── client-matter ──
    ("client-matter",
     "Client Meridian Corp — retail banking division; primary contact General Counsel Sarah "
     "Okafor; billed under matter 2026-0417.", "intake", 0.90),
    ("client-matter",
     "Delgado v. Meridian: employment dispute; the contested issue is the arbitration clause "
     "in the 2022 offer letter.", "file", 0.90),
    ("client-matter",
     "Nunez appeal: appealing the summary-judgment finding on the amount-in-controversy "
     "threshold for jurisdiction.", "file", 0.88),
    ("client-matter",
     "Conflict check cleared for all Meridian matters on 2026-06-01; no adverse representation.",
     "conflicts", 0.90),
]

SESSION_NOTE = """\
# Case prep — Delgado matter · verification pass

Ran a reference-system verification pass on the precedent leaves before drafting the
motion to compel litigation.

- **A reference-system search for "Meridian v. Calloway Holdings (2024)" returned no such
  decision** — the citation does not resolve to any decision on file. It appears fabricated.
  Do NOT rely on it in the filing; flag for attorney review before anything is filed.
- The other cited precedents checked out and resolve correctly.

Reminder: a reference-system "not found" is evidence the cite is unsupported — it is not a
ruling on the merits. Verify before filing; that is the professional duty.
"""


def build_tree():
    tree = kt.new_tree() if hasattr(kt, "new_tree") else {
        "version": "1.0", "instance": "advocate-demo",
        "root_hash": "", "branches": {}, "combined_root_hash": "",
    }
    plant_id = None
    for i, (branch, content, source, conf) in enumerate(LEAVES):
        leaf = kt.add_knowledge(tree, branch, content, source=source, confidence=conf)
        if i == 0:
            plant_id = leaf["id"] if isinstance(leaf, dict) else _last_leaf_id(tree, branch)
    return tree, plant_id


def _last_leaf_id(tree, branch):
    return tree["branches"][branch]["leaves"][-1]["id"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "fixtures"))
    ap.add_argument("--memory-date", default="2026-07-17",
                    help="date stamp for the verification session note")
    args = ap.parse_args()

    tree, plant_id = build_tree()

    os.makedirs(args.out, exist_ok=True)
    base_mem = os.path.join(args.out, "base", "memory")
    os.makedirs(base_mem, exist_ok=True)

    tree_path = os.path.join(args.out, "seed_tree.json")
    kt.save_tree(tree, tree_path)

    note_path = os.path.join(base_mem, f"{args.memory_date}.md")
    with open(note_path, "w") as f:
        f.write(SESSION_NOTE)

    # Record which leaf is the plant so the recorder/replay can reference it by id
    # WITHOUT the gardener ever being told (this file is demo bookkeeping, not a
    # gardener input — run_demo.sh greps prove no leaf id reaches the gardener).
    with open(os.path.join(args.out, "PLANT_ID.txt"), "w") as f:
        f.write(plant_id + "\n")

    n = sum(len(b["leaves"]) for b in tree["branches"].values())
    print(f"seed tree: {n} leaves across {len(tree['branches'])} branches -> {tree_path}")
    print(f"plant leaf id: {plant_id}  (precedent / fabricated Meridian v. Calloway cite, conf 0.95)")
    print(f"verification note ({args.memory_date}) -> {note_path}")


if __name__ == "__main__":
    main()
