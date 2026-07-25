# PCIS Agent Plugin

Give any compatible agent a self-challenging, tamper-evident claim record — persistent memory that gets audited, not just stored.

## Installation

1. Clone or install PCIS:

   ```bash
   git clone https://github.com/dwty11/pcis.git
   # or, from Russian networks:
   git clone https://gitverse.ru/dwty/pcis.git
   cd pcis
   pip install -e .
   ```

2. Copy (or symlink) the `agent-plugin/` directory into wherever your agent framework loads plugins from. The exact path depends on your framework — common examples:

   ```bash
   # Generic example — replace with your framework's actual plugins path
   cp -r agent-plugin/ /path/to/your/agent/plugins/pcis/
   ```

3. Configure the plugin in your agent config:

   ```json
   {
     "plugins": {
       "pcis": {
         "base_dir": "~/.pcis"
       }
     }
   }
   ```

4. Initialize the PCIS tree (first time only):

   ```bash
   pcis init --dir ~/.pcis
   ```

## Available Tools

Once installed, your agent gains three tools:

| Tool | Description |
|------|-------------|
| `pcis_add(branch, content, source, confidence)` | Add a knowledge leaf to the tree |
| `pcis_search(query, top_k)` | Search the knowledge tree by meaning |
| `pcis_status()` | Show tree integrity, branch counts, and root hash |

`pcis_search` returns a list of `{score, leaf_id, branch, content, confidence}`
dicts, ranked by cosine similarity. `content` is the leaf's **full text** — it
is deliberately not truncated, because a clip can drop a trailing qualifier
that reverses the claim, and an agent cannot tell it received half a sentence
the way a human reading an ellipsis can.

It requires a semantic search index, which is built separately and needs a
local Ollama embedding model:

```bash
python3 core/knowledge_search.py --reindex
```

Without that index `pcis_search` returns an empty list rather than raising —
so an agent that gets no results should check the index before concluding the
tree is empty. `pcis_add` indexes new leaves incrementally, but only if an
index already exists.

## Retrieval tracing

Every `pcis_search` call appends a record to
`$PCIS_BASE_DIR/data/provenance-ledger.jsonl` describing which leaves fed the
result, a hash of each leaf's content **as retrieved**, and the Merkle root at
that moment. Those leaf ids can later be re-verified against the tree.

Note this means a read operation writes a file. Set
`PCIS_TRACE_RETRIEVAL=0` to disable it. A trace that cannot be written never
fails the search — the failure is reported on stderr and retrieval returns
normally.

What a trace establishes is narrow and worth stating precisely: that these
leaves were retrieved and still match the record. It is **not** evidence that
an answer used them, was grounded in them, or is correct — nothing compares
answer text to leaf content. And because a missing record leaves no gap to
notice, the ledger does not demonstrate coverage; only that traced retrievals
are traced.

## Session Lifecycle

On session start, the plugin automatically:
- Verifies Merkle tree integrity
- Loads tree status (branch count, leaf count, root hash)
- Reports any integrity mismatches

## Configuration

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `base_dir` | string | `~/.pcis` | PCIS data directory |

## Requirements

- Python 3.10+
- PCIS >= 1.2.0
