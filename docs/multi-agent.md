# Multi-Agent Support — Specification

## Overview

Multiple AI agents can share a single PCIS knowledge tree instance. Each agent
is identified by a unique `agent_id` (string), and every leaf tracks which agent
authored it. The shared tree file uses the existing file-level locking
(`tree_lock`) for safe concurrent access.

## Agent Identity

- Each agent has a unique `agent_id` (string, e.g. `"agent-research"`, `"agent-ops"`).
- Agents register themselves in `tree["agents"]` — a dict keyed by `agent_id`
  containing metadata (display name, description, registration timestamp).
- Registration is idempotent — re-registering an existing agent updates metadata.

## Leaf Authorship

- Every leaf gets an `author` field set to the `agent_id` of the agent that
  created it.
- Leaves created before multi-agent support have `author: null` (backward
  compatible).

## Shared Tree File

- The tree file at `$PCIS_BASE_DIR/data/tree.json` is shared by all agents.
- File-level locking via `tree_lock()` (fcntl) ensures safe concurrent writes.
- Each agent loads the tree, acquires the lock, writes, and releases — same as
  single-agent mode.

## Concurrency

- Writes are **append-only**: `add_knowledge_as()` adds new authored leaves. There
  is no in-place leaf-modification path, so there is no last-write-wins conflict to
  resolve at the leaf level.
- Concurrent writers are serialized by the file lock (`tree_lock()`, fcntl), so no
  write is lost or interleaved.
- Authorship is recorded (the `author` field), not enforced — see Access Control.

> **Roadmap (not implemented).** A per-leaf `belief_history` recording the before/after
> state on every confidence or content change would give a full mutation audit trail.
> The tree is append-only today and does not track leaf edits; this is a future
> enhancement, not a current guarantee.

## Access Control

- **Read:** all agents can read all branches. No read restrictions.
- **Write:** the tree records authorship — `add_knowledge_as()` sets each new
  leaf's `author` field — but **does not currently enforce write permissions**.
  Any agent can write to any branch; authorship is a record of *who wrote* a
  leaf, not a gate on who was allowed to.
- A `tree["branch_permissions"]` map (`branch_name -> list[agent_id]`) is
  reserved for a future enforcement layer. It is **not** consulted by
  `add_knowledge_as()` today.

## Discovery

- Agents can query "what did agent X add recently?" via
  `get_agent_contributions(tree, agent_id, since=datetime)`.
- `list_agents(tree)` returns all registered agents and their metadata.

## Data Model Changes

```json
{
  "agents": {
    "agent-research": {
      "display_name": "Research Agent",
      "description": "Handles literature review and fact extraction",
      "registered": "2026-04-20 12:00:00 UTC"
    }
  },
  "branches": {
    "technical": {
      "leaves": [
        {
          "id": "...",
          "content": "...",
          "author": "agent-research",
          "..."
        }
      ]
    }
  }
}
```
