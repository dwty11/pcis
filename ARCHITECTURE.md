# PCIS Architecture — Six Contributions

## 1. Persistent Knowledge Tree
PCIS stores agent knowledge as a structured tree of leaves, not a flat log or vector index. Each leaf carries a fact, a branch tag, a confidence score, a source reference, and a timestamp. Knowledge is organized by domain, queryable by semantic search, and human-readable at every level. The tree persists across sessions — the agent wakes up knowing what it knew when it last ran.

## 2. Merkle Integrity Verification
Every state of the knowledge tree is cryptographically hashed using a Merkle structure. When the agent boots, it computes the current root hash and compares it to the last recorded state. A mismatch means the tree was modified outside normal operation — drift, tampering, or corruption. This makes the agent's memory tamper-evident and auditable: you can prove what the agent knew at any point in time.

## 3. Adversarial Pass via External LLM
PCIS runs a periodic adversarial pass where an external LLM is given existing knowledge leaves and asked to challenge them. The adversary is not looking for errors — it is looking for contradictions, outdated assumptions, and knowledge that no longer holds given new context. Where challenges succeed, COUNTER leaves are generated and staged for review. The tree is not blindly updated — it is pressure-tested.

## 4. Gap-Scan (Completeness, Not Just Correctness)
Most verification systems ask: is what the agent knows correct? Gap-scan asks a different question: what should the agent know that it doesn't? The scanner reads recent session logs and external inputs, extracts significant facts and decisions, and cross-checks them against the knowledge tree. Entries that are missing — never committed, or committed but since pruned — are staged for addition. Correctness and completeness are orthogonal problems. PCIS solves both.

## 5. Pruning Protocol
A knowledge tree that only grows becomes a liability. PCIS includes a pruning protocol that identifies leaves with low confidence scores, high age relative to their domain, or explicit supersession by newer leaves. Pruning is not deletion — candidates are flagged, reviewed, and removed only when confirmed stale. The goal is a tree that stays sharp: high-signal, low-noise, trustworthy.

## 6. Model-Agnostic Design
PCIS does not depend on any specific language model. The knowledge tree, integrity layer, adversarial pass, and gap-scan all operate through a standard API interface. The underlying model — GPT-4, Claude, Llama, or any locally-hosted model (including GigaChat for on-prem deployments) — can be swapped without touching the memory layer. This means no vendor lock-in, no retraining required when models change, and the ability to run entirely on-premises with local models.

## PCIS and External Memory Continual Learning

The central challenge in continual learning is the stability-plasticity tradeoff: systems that learn new things tend to forget old ones (catastrophic forgetting), and systems that preserve old knowledge tend to resist new learning. Most approaches address this by modifying training procedures or weight update rules.

PCIS takes a different approach: externalize memory entirely, and manage the stability-plasticity tradeoff at the knowledge layer rather than the weight layer.

The mapping is direct:
- **Replay buffer** → the knowledge tree (prior knowledge is always available, never overwritten by new model updates)
- **Stability** → the adversarial gardener (nightly pressure-testing prevents overconfidence in stale beliefs)
- **Plasticity** → gap-scan (identifies what's missing, drives targeted knowledge addition)
- **Forgetting** → pruning protocol (explicit, deliberate removal of confirmed-stale leaves)

The result: an agent that accumulates knowledge over time, challenges its own beliefs, and can prove what it knew and when — without retraining, without weight updates, and without losing prior context.

## Identity Portability

The Merkle root hash is determined solely by tree content — not by which model processed it. This is an enforced invariant (tested in `tests/test_pcis.py::TestIdentityPortability`): the same knowledge tree produces the same root hash whether the underlying LLM is GPT-4, Claude, Llama, or any other model.

This means the root hash is a model-agnostic identity. An agent can switch underlying models mid-deployment — or run the same tree through multiple models simultaneously — and the cryptographic identity remains unchanged. Memory follows the agent, not the model.

---

## Codebase Reference

### Core Modules

**`core/knowledge_tree.py`** — The foundation. Everything else depends on this. It defines the data model: a tree has branches (e.g. "identity", "lessons", "technical", "relationships"), and each branch holds leaves. Each leaf carries an id, hash, content, source, confidence score, created timestamp, and promoted_to field.

Four critical functions:
- `hash_leaf` — SHA-256 from content + branch + timestamp
- `compute_branch_hash` — sorts all leaf hashes in a branch and hashes them together
- `compute_root_hash` — takes all branch hashes, iteratively pairs and hashes upward in a binary tree until one root remains
- `tree_lock()` — context manager wrapping the full read-modify-write cycle under an exclusive file lock: load → mutate → write, all atomic

Also provides `add_knowledge` (with input validation), `prune_leaf`, `diff_trees`, and a CLI for `--add`, `--show`, `--prune`, `--diff`, `--export`, `--root`. Tree persists as `data/tree.json`.

---

**`core/verify_memory.py`** — Integrity checking for the codebase itself, not the knowledge tree. Tracks a hardcoded list of core files, hashes each with SHA-256, and computes a Merkle-style root over all of them. On first run (`--init`), writes a manifest to `data/integrity/manifest.json`. On subsequent runs, recomputes all hashes and compares — any change is reported by filename. `--update` accepts the current state as the new baseline. `--status` returns CLEAN/CHANGED/MISSING for scripting. Run this at session start to verify your own code was not modified between sessions.

---

**`core/gardener.py`** — The adversarial maintenance agent. Loads the knowledge tree, formats it as readable text, and sends it to a local LLM (Qwen3:14b via Ollama) asking it to find echo chambers, generate counter-arguments, identify cross-branch connections, and flag stale leaves. The LLM responds in pipe-delimited format (`COUNTER|branch|content|confidence`, `SYNAPSE|content|confidence`, `FLAG|leaf_id|reason`); staged items are written as JSONL for reliable parsing. If parsing yields zero results, it retries once.

Tiered commit system:
- Counter-leaves targeting operational branches (`technical`, `lessons`) → auto-committed
- Counter-leaves targeting constitutional branches (`identity`, `philosophy`) → staged for human review
- Synapses (cross-branch connections) → always staged

A separate `--gap-scan` mode reads daily memory notes, extracts key facts via LLM, then checks each against the tree via semantic search — anything below similarity 0.6 is flagged as a gap. Output: `gardener-log.md`, `gardener-staging.md`, and a notify flag file. Designed as a nightly cron job.

---

**`core/knowledge_search.py`** — Semantic search over the knowledge tree. Uses a local embedding model (`nomic-embed-text`, 768 dimensions) via Ollama. `--reindex` walks every leaf, generates an embedding by sending `[branch] content (source: source)` to Ollama's `/api/embeddings` endpoint, and stores results in `data/search-index.json`. Search embeds the query, computes cosine similarity against every stored vector, and returns top-k results. `incremental_index` adds a single leaf without a full rebuild. `search_for_briefing` returns pre-formatted results for session briefing injection. All vector math and API calls implemented from scratch — no external libraries beyond `urllib` and `math`.

---

**`core/knowledge_prune.py`** — Active forgetting. Analyzes the tree for leaves that should be removed or reviewed:
- `--stale` — leaves older than N days (default 90)
- `--low-confidence` — leaves below a threshold
- `--branch-health` — per-branch metrics: average confidence, spread, oldest leaf age; warns about echo chambers (confidence too uniform or too high)
- `--auto-flag` — rule-based candidates: very low confidence (<0.5), old + low confidence (>180 days, <0.7), or empty content
- `--execute --yes` — removes flagged candidates under `tree_lock()`
- `--review` — interactive walkthrough: keep, prune, or refresh confidence on each candidate

All prune actions logged to `data/prune-log.json`.

---

### Demo Modules

**`demo/server.py`** — Flask web server exposing the knowledge tree through a REST API. Endpoints: `/api/boot` (Merkle root + file integrity), `/api/tree` (full branch structure with leaf counts), `/api/query` (keyword search scored by hits × confidence), `/api/adversarial` (COUNTER-prefixed leaves linked to their originals), `/api/adversarial-validation` (saved validation run results), `/api/status` (system health). Binds to `127.0.0.1:5555`.

**`core/adversarial_validator.py`** — External adversarial validation agent. Picks highest-confidence leaves, sends them to an external LLM API for challenge, parses counter-leaves, and saves the full run (with before/after Merkle roots) to JSON. Complements the nightly gardener: where `gardener.py` runs locally and continuously, `adversarial_validator.py` is the external second opinion — a different model, a different perspective, no shared context with the system it is auditing.

**`demo/demo_tree.json`** — Synthetic knowledge tree: 5 branches, 19 leaves, zero personal data (enforced by a test). Used to seed `data/tree.json` and drive the demo server.

**`demo/index.html`** — Single-file frontend. Five tabs: Boot (live Merkle verification), Knowledge Tree (branch browser), Query (keyword search), Adversarial (counter-leaves with originals), External LLM Validation. Dark theme, vanilla JS, no framework.

---

### Tests (`tests/test_pcis.py`)

19 tests across 7 classes (18 original + identity portability):

| Class | What it verifies |
|-------|-----------------|
| `TestMerkleHashing` | Root hash changes on add/edit, determinism, branch-hash order independence, tamper detection |
| `TestAdversarialCounters` | COUNTER leaf detection, challenged-ID parsing, normal leaves not misidentified |
| `TestDemoTreeIntegrity` | Demo tree schema, confidence ranges, root hash presence, no personal data leakage |
| `TestCrossModuleHashConsistency` | All modules produce identical root, branch, and leaf hashes for the same data |
| `TestAddKnowledgeValidation` | Empty and oversized content rejected with `ValueError` |
| `TestConcurrentSaveTree` | Two threads × 5 writes under `tree_lock()` → exactly 10 leaves, zero data loss |
| `TestIdentityPortability` | Root hash identical across model configs — model-agnostic identity enforced |

Run with: `python -m pytest tests/ -v`

---

### Config & Infrastructure

**`setup.sh`** — Runs `pip install -r requirements.txt`, creates `data/`, copies `demo_tree.json` into it as the starting tree.

**`requirements.txt`** — Just `flask>=3.0.0`. The core modules have zero external dependencies — all vector math, hashing, and API calls use the Python standard library.

**`config.example.json`** — Template with `base_dir`, `llm_api_key`, `model_name`, `demo_mode`. Copy to `config.json` before running adversarial validation.

**`.github/workflows/ci.yml`** — GitHub Actions running the full test suite on Python 3.10, 3.11, and 3.12 on every push and PR to `main`.
