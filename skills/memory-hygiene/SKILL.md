---
name: memory-hygiene
description: "Proactive PCIS tree maintenance for AI agents. Use periodically (every few sessions) to detect stale knowledge, echo chambers, and pruning candidates. Not for daily use — for deliberate tree health checks."
---

# PCIS Memory Hygiene

Knowledge trees degrade without maintenance. Confidence inflates, contradictions accumulate, stale leaves persist. This skill is for deliberate, periodic tree health checks — not something you run every session.

**Run this every 5-10 sessions, or any time the tree feels unreliable.**

---

## Step 1 — Check Branch Health

```bash
python3 core/knowledge_prune.py --branch-health
```

Red flags to look for:
- **HIGH AVG CONFIDENCE, LOW SPREAD** — echo chamber. Every leaf agrees. The adversarial gardener needs to run.
- **No COUNTER leaves** — beliefs are never being challenged. That is not intellectual health; it is intellectual stasis.
- **Leaves >90 days old with confidence >0.9** — time-sensitive knowledge that may be outdated.

---

## Step 2 — Run the Adversarial Gardener (dry run first)

```bash
# See what the gardener would challenge — without committing
python3 core/gardener.py --dry-run

# If the challenges look valid, run for real
python3 core/gardener.py
```

The gardener finds high-confidence leaves and generates external LLM challenges. It commits COUNTER leaves where challenges hold. This is how the tree stays honest.

**After gardener runs:** Check what was added.
```bash
python3 core/knowledge_tree.py --show --branch lessons
```

---

## Step 3 — Review Pruning Candidates

```bash
python3 core/knowledge_prune.py --flag-stale
```

This surfaces leaves that are candidates for removal: low confidence, no reinforcement, contradicted by newer leaves. **Review manually before deleting anything.** The pruner flags; you decide.

---

## Step 4 — Verify Root After Any Changes

```bash
python3 core/verify_memory.py --update
```

Always update the Merkle root after any gardener run or manual pruning. A stale root is a broken integrity guarantee.

---

## Signs the Tree Needs Hygiene Now (Don't Wait)

- You notice the agent contradicting itself across sessions
- Two leaves in the same branch make opposite claims, neither is a COUNTER
- Confidence on most leaves is 0.9+ across the board
- A leaf references a fact that you know has changed but the tree still holds the old value
- The root hash hasn't changed in 30+ sessions despite active use

---

## What NOT to Do

- **Do not run gardener on every session** — it burns LLM budget and generates noise. It is a deliberate health check, not a background process.
- **Do not delete leaves without reading them** — pruning candidates are flagged, not auto-deleted. The decision is yours.
- **Do not mistake COUNTER leaves for errors** — a COUNTER leaf is healthy epistemic structure. It means the tree is capable of disagreeing with itself, which is more honest than false consensus.
