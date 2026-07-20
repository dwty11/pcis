# PCIS Agent Plugin

Give any compatible agent persistent, cryptographically verifiable long-term memory.

## Installation

1. Clone or install PCIS:

   ```bash
   git clone https://github.com/dwty11/pcis.git
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
