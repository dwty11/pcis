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

## Conflict Resolution

- **Last-write-wins** at the leaf level — if two agents modify the same leaf
  concurrently, the last writer's version persists.
- Every confidence change and content edit is recorded in `belief_history`,
  providing a full audit trail regardless of which agent made the change.
- No leaf is ever silently overwritten — the history log always contains both
  the before and after state.

## Access Control

- **Read:** all agents can read all branches. No read restrictions.
- **Write:** configurable per branch via `tree["branch_permissions"]` (optional).
  When present, maps `branch_name -> list[agent_id]`. If a branch has no entry,
  all agents can write. If it has an entry, only listed agents can write.
- Permissions are advisory — enforced by `add_knowledge_as()`, not at the
  file-system level.

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
