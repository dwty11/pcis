---
name: knowledge-search
description: "How to search the PCIS knowledge tree effectively. Use before answering questions, before starting research, before recommending anything the tree might already know. Covers keyword search, semantic search, and branch-scoped queries."
---

# PCIS Knowledge Search

Before answering a question, starting research, or making a recommendation — check the tree first. The most expensive mistake is re-learning something you already know.

---

## Rule: Search Before You Reason

Run a search before any of these:
1. Answering a domain question ("what do we know about X?")
2. Starting research on a topic
3. Recommending a model, tool, or approach
4. Making an architectural decision
5. Proposing a change that might conflict with an existing constraint

The search takes two seconds. The cost of ignoring it is repeating a known mistake.

---

## Basic Search

```bash
# Keyword search — always available, no Ollama required
python3 core/knowledge_search.py "<your query>"

# Example
python3 core/knowledge_search.py "database performance"
python3 core/knowledge_search.py "what do we know about deployment"
```

---

## Semantic Search

Semantic search finds conceptually related leaves even when keywords don't match. Requires Ollama with `nomic-embed-text`.

```bash
# Index first (only needed once, or after adding many new leaves)
python3 core/knowledge_search.py --reindex

# Then search by meaning
python3 core/knowledge_search.py "how should we handle contradictory evidence"
```

---

## Branch-Scoped Queries

When you know what kind of knowledge you need, scope the search:

```bash
# What behavioral rules are active?
python3 core/knowledge_tree.py --show --branch constraints

# What is the current project state?
python3 core/knowledge_tree.py --show --branch state

# What lessons have been learned?
python3 core/knowledge_tree.py --show --branch lessons

# Full tree overview
python3 core/knowledge_tree.py --show
```

---

## Reading Search Results

Each result includes:
- **content** — the leaf text
- **confidence** — how certain this knowledge is (0.0–1.0)
- **source** — where it came from
- **hash** — unique leaf identifier (use this to reference a leaf in COUNTER entries)

**Confidence interpretation:**
- `0.9–1.0` — treat as fact unless you have strong contradicting evidence
- `0.7–0.89` — reliable, but worth double-checking for high-stakes decisions
- `0.5–0.69` — hypothesis; verify before acting on it
- `<0.5` — flagged for review; use with caution

---

## When Search Returns Nothing

No results means one of two things:
1. The tree genuinely doesn't know — proceed with research, then commit what you learn
2. The query terms don't match existing leaf text — try rephrasing or use `--reindex` + semantic search

Do not interpret empty results as "this is new territory." Check with a broader query first.

---

## Verify What You Found Is Current

The tree can hold outdated knowledge. After reading a leaf, ask:
- Is the `source` date recent enough to be reliable for this decision?
- Is there a COUNTER leaf (`COUNTER: [this-leaf-id]`) that challenges it?
- Does the confidence level match the stakes of what I'm about to do?

If a leaf is outdated, add a new leaf with the current fact and a COUNTER reference. Do not silently use stale knowledge.

---

## Integrity Check Before High-Stakes Searches

For decisions where being wrong has real cost:

```bash
python3 core/verify_memory.py
```

If this returns anything other than CLEAN — stop. The tree state is not verified. Do not use search results for decisions until integrity is confirmed.
