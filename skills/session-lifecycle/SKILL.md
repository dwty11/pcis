---
name: session-lifecycle
description: "PCIS session bootstrap and commit protocol for AI agents. Use at conversation start (load context from tree) and conversation end (commit new knowledge). Required reading before any PCIS integration."
---

# PCIS Session Lifecycle

PCIS is not a database you query on demand. It is your agent's persistent identity. This file tells you when and how to use it — at the boundaries of every session.

---

## Session Start — Load Context

Before doing anything else, orient yourself in the knowledge tree.

```bash
# 1. Verify tree integrity — if this fails, stop and report
python3 core/knowledge_tree.py --root
python3 core/verify_memory.py

# 2. Load relevant context for the session topic
python3 core/knowledge_search.py "<what this session is about>"

# 3. Load any standing constraints or active state
python3 core/knowledge_tree.py --show --branch constraints
python3 core/knowledge_tree.py --show --branch state
```

**If integrity check returns CHANGED or MISSING:** Do not proceed. Report the discrepancy. The tree may have been tampered with or corrupted.

**If integrity check returns CLEAN:** Proceed. The tree state you are reading is verified.

---

## During the Session

Use the tree as working memory, not just a reference:

- When the user states a new fact or preference → commit it before the session ends
- When a decision is made → commit it with reasoning as `source`
- When you discover a contradiction with an existing leaf → add a COUNTER leaf; do not silently overwrite
- When two pieces of knowledge connect → note the connection in the leaf text

Do not accumulate knowledge mentally and commit at the end in bulk. Commit as you go when stakes are high.

---

## Session End — Commit New Knowledge

At the end of every session where something meaningful happened:

```bash
# Add new knowledge (repeat for each significant fact, decision, or lesson)
python3 core/knowledge_tree.py \
  --add <branch> \
  "<what was learned or decided>" \
  --source "session-YYYY-MM-DD" \
  --confidence <0.0-1.0>

# Update Merkle root — do this last, after all commits
python3 core/verify_memory.py --update
```

**Branch selection:**
| What happened | Branch |
|---|---|
| New fact about the domain | `technical` |
| Decision made | `state` |
| Lesson from a mistake | `lessons` |
| Behavioral rule established | `constraints` |
| Long-term belief or principle | `identity` |

**Confidence guide:**
- `1.0` — direct instruction, explicit order, verified fact
- `0.9` — strong inference from clear evidence
- `0.7-0.85` — reasonable conclusion, some uncertainty
- `0.5-0.65` — hypothesis, low confidence, needs verification

---

## What NOT to Do

- **Do not skip session-end commits** — "mental notes" do not survive session restarts. The tree does.
- **Do not overwrite existing leaves** — add a COUNTER leaf with `COUNTER: [leaf-id]` prefix if you disagree with existing knowledge.
- **Do not commit bulk summaries** — one fact per leaf. "Many things happened" is not a leaf.
- **Do not run `--update` before committing new leaves** — update the root after all new knowledge is in.
