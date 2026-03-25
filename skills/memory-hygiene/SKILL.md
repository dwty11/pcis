---
name: memory-hygiene
description: "Proactive PCIS tree maintenance for AI agents. Covers before-you-store discipline, confidence management, branch selection, and what to do when the gardener runs. Use periodically for deliberate tree health checks."
---

# PCIS Memory Hygiene

Knowledge trees degrade without maintenance. Confidence inflates, contradictions accumulate, stale leaves persist. This skill covers two things: discipline at commit time (preventing problems), and periodic health checks (fixing them).

---

## Before Storing Anything

```bash
# Check if this knowledge already exists
python3 core/knowledge_search.py "<what you're about to commit>"
```

- If a similar leaf exists at equal or higher confidence: do not duplicate
- If a similar leaf exists but is outdated: add the new leaf and note the supersession in the content
- If no match: proceed with commit

---

## Confidence Management

Never default to 1.0. The scale means something:

| Confidence | Meaning |
|---|---|
| `1.0` | User directly stated this; I witnessed it |
| `0.9+` | Verified truth, multiple sources agree |
| `0.7–0.85` | Well-sourced fact, minor uncertainty |
| `0.5–0.65` | Inference or pattern; should be verified |
| `<0.5` | Hypothesis only; flag for review |

Claims from external sources: `0.6–0.8` depending on source reliability.
If uncertain about confidence: use `0.7`.

---

## Branch Selection

| Branch | What belongs here |
|---|---|
| `identity` | Who the agent is, standing orders, core principles |
| `philosophy` | Reasoning frameworks, epistemics, meta-beliefs |
| `lessons` | Operational learnings, mistakes, corrections |
| `technical` | Technical facts, architecture decisions, tool knowledge |
| `relationships` | People, organizations, interaction history |
| `constraints` | Protected standing orders — never auto-pruned |
| `state` | Current project state, active facts |

The `constraints` branch is constitutional. Leaves here survive gardener pruning. Use it for rules that must hold regardless of what the gardener challenges.

---

## Periodic Health Check (Every 5–10 Sessions)

```bash
# Check for echo chambers and stale knowledge
python3 core/knowledge_prune.py --branch-health

# Run adversarial challenge (dry run first)
python3 core/gardener.py --dry-run
python3 core/gardener.py  # commit if challenges look valid

# Surface pruning candidates
python3 core/knowledge_prune.py --flag-stale

# Update root after any changes
python3 core/verify_memory.py --update
```

**Red flags in branch health output:**
- HIGH AVG CONFIDENCE, LOW SPREAD — echo chamber; gardener needs to run
- No COUNTER leaves in any branch — beliefs are never being challenged
- Leaves >90 days old with confidence >0.9 — may be outdated

---

## When the Gardener Runs

- Counter-leaves on operational branches (`lessons`, `technical`) are auto-committed
- Counter-leaves on constitutional branches (`identity`, `philosophy`, `constraints`) are staged for user review
- Review staged challenges: `python3 core/gardener.py --apply-staging`

**COUNTER leaves are healthy.** A tree that can disagree with itself is more honest than one that can't. Do not treat COUNTER leaves as errors — they are epistemic structure.

---

## Signs the Tree Needs Hygiene Now

- The agent contradicts itself across sessions
- Two leaves in the same branch make opposite claims, neither is a COUNTER
- Confidence on most leaves is 0.9+ across the board
- A leaf references a fact you know has changed
- The root hash hasn't changed in 30+ sessions despite active use
