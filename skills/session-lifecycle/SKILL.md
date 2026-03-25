---
name: session-lifecycle
description: "PCIS session bootstrap and commit protocol for AI agents. Use at conversation start (verify integrity, load context) and conversation end (commit new knowledge, update Merkle root). Required reading before any PCIS integration."
---

# PCIS Session Lifecycle

PCIS is not a database you query on demand. It is your agent's persistent identity. This file tells you when and how to use it — at the boundaries of every session.

---

## Conversation Start

Run these steps before doing anything else.

```bash
# 1. Verify tree integrity — if not CLEAN, stop and alert the user
python3 core/verify_memory.py --status

# 2. Search for context relevant to the user's first message
python3 core/knowledge_search.py "<what this session is about>"

# 3. Check for pending gardener notifications
cat memory/gardener-pending-notify.flag 2>/dev/null
```

**If integrity check returns CHANGED or MISSING:** Do not proceed. Report the discrepancy. The tree may have been tampered with or corrupted. Searching a compromised tree is pointless — verify first, then trust.

**If a gardener flag exists:** Inform the user: "The gardener flagged items for review. Run `python3 core/gardener.py --apply-staging` when ready."

**If CLEAN:** Proceed. Everything you read from the tree is cryptographically verified.

---

## During the Conversation

- When the user mentions an entity (company, person, project) — search the tree before responding
- When the user corrects you — store the correction immediately as a new leaf with `--source "user-correction"`
- When you make a decision or recommendation — store the reasoning with source and confidence
- When you learn something worth retaining — store it immediately, don't batch for later
- When you discover a contradiction with an existing leaf — add a COUNTER leaf; do not silently overwrite

---

## Conversation End

Review the session for knowledge worth committing. Store 1-3 high-value leaves — not a brain dump.

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

**Do not store:** trivial exchanges, temporary file paths, information already in the tree at equal or higher confidence.

**Branch selection:**
| What happened | Branch |
|---|---|
| New domain fact or architecture decision | `technical` |
| Current project state | `state` |
| Lesson from a mistake or correction | `lessons` |
| Behavioral rule or standing order | `constraints` |
| Long-term belief or principle | `identity` |
| People, organizations, interaction history | `relationships` |

**Confidence guide:**
- `1.0` — user directly stated this; I witnessed it
- `0.9` — verified fact, strong evidence
- `0.7–0.85` — well-sourced, some uncertainty
- `0.5–0.65` — hypothesis or inference; needs verification
- Never default to 1.0 — reserve it for direct user statements only
