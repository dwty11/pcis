---
name: knowledge-search
description: "How to search the PCIS knowledge tree effectively. Use before answering questions, before starting research, before recommending anything the tree might already know. Covers integrity check, keyword search, semantic search, and branch-scoped queries."
---

# PCIS Knowledge Search

Before answering a question, starting research, or making a recommendation — check the tree first. The most expensive mistake is re-learning something you already know.

---

## Rule: Verify Before You Search

Searching a tampered tree gives you tampered answers. One line, every time:

```bash
python3 core/verify_memory.py --status
```

If this returns anything other than CLEAN — stop. Do not use search results for decisions until integrity is confirmed.

---

## Rule: Search Before You Reason

Run a search before any of these:
1. Answering a domain question
2. Starting research on a topic
3. Recommending a model, tool, or approach
4. Making an architectural decision
5. Responding to a question about a known entity (company, person, project)

The search takes two seconds. Skipping it means repeating known mistakes.

---

## Basic Search (Always Available)

```bash
python3 core/knowledge_search.py "<your query>" --top 5
```

---

## Semantic Search (Requires Ollama + nomic-embed-text)

Finds conceptually related leaves even when keywords don't match.

```bash
# Index first (once, or after many new leaves)
python3 core/knowledge_search.py --reindex

# Search by meaning
python3 core/knowledge_search.py "how should we handle contradictory evidence"
```

---

## Branch-Scoped Queries

When you know what kind of knowledge you need:

```bash
python3 core/knowledge_tree.py --show --branch constraints   # standing rules
python3 core/knowledge_tree.py --show --branch state         # current project state
python3 core/knowledge_tree.py --show --branch lessons       # past mistakes
python3 core/knowledge_tree.py --show                        # full tree
```

---

## Reading Results

Each result includes:
- **content** — the leaf text
- **confidence** — certainty (`0.0–1.0`)
- **source** — provenance
- **hash** — unique leaf ID (use this when writing COUNTER entries: `COUNTER: [hash]`)

**Acting on results:**
- `0.9–1.0` — treat as fact unless you have strong contradicting evidence
- `0.7–0.89` — reliable; worth verifying for high-stakes decisions
- `0.5–0.69` — hypothesis; verify before acting
- `<0.5` — flagged for review; use with caution

---

## When Search Returns Nothing

Two possibilities:
1. The tree genuinely doesn't know — proceed, then commit what you learn
2. Query terms don't match — try rephrasing, or use `--reindex` + semantic search

Do not treat empty results as confirmation this is new territory. Try a broader query first.

---

## Verify Before Acting on High-Stakes Results

For decisions where being wrong has real cost:
- Is the `source` date recent enough to be reliable?
- Is there a COUNTER leaf challenging this result?
- Does the confidence level match the stakes of the decision?

If a leaf is outdated: add a new leaf with the current fact and reference the old one. Do not silently use stale knowledge.
