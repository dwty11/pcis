# PCIS Architecture

PCIS is built around one idea: an agent's knowledge should be **challenged**, not just stored and signed. The adversarial pass — the gardener — is what makes PCIS more than a tamper-evident log; the knowledge tree and its Merkle integrity are the substrate it runs on.

## 1. Adversarial Pass (the gardener)
PCIS runs a periodic adversarial pass where a local LLM — the gardener, on Ollama or MLX — is given the knowledge tree and told to attack its highest-confidence claims: the branches with high mean confidence and low spread, using the last five days of session memory as context. Where a challenge holds, a COUNTER leaf is generated. Where a pass raises no counter for a claim — a routine outcome with a small local model — nothing is written for it: no counter leaf, no synapse, no confidence change. A challenge that did not happen is never put on the record as one. The commit is tiered: routine counters on operational branches (`technical`, `lessons`) auto-commit, while challenges to constitutional beliefs (`identity`, `philosophy`, `core`) and new synapses are staged for human review. The tree is not blindly updated — it is pressure-tested. This is what separates PCIS from a tamper-evident log: the record attacks itself.

## 2. Persistent Knowledge Tree
PCIS stores agent knowledge as a structured tree of leaves, not a flat log or vector index. Each leaf carries a fact, a branch tag, a confidence score, a source reference, and a timestamp. Knowledge is organized by domain, queryable by semantic search, and human-readable at every level. The tree persists across sessions — the agent wakes up knowing what it knew when it last ran.

## 3. Merkle Integrity Verification
Every state of the knowledge tree is fingerprinted using a cryptographic hash chain. Leaf hashes are combined pairwise into a binary Merkle tree at the branch level, and branch roots are combined the same way into the tree root. When the agent boots, it recomputes the root hash from content up and compares it to the last recorded state. A mismatch means the tree was modified outside normal operation — drift, tampering, or corruption.

Beyond tamper detection, the binary tree structure enables **Merkle inclusion proofs**: `generate_proof(tree, branch, leaf_id)` produces a compact proof path (list of sibling hashes) that a third party can use to verify a specific leaf existed in the tree at a given state — without possessing the full tree. `verify_proof(leaf_hash, proof, expected_root)` is a standalone function with zero dependencies on the tree — provable inclusion in the Certificate-Transparency sense. Inclusion proofs are substrate for the accountability story; what makes the record more than tamper-evident is the adversarial pass in §1.

## 4. The Off-Machine Signing Boundary
The Merkle root proves the record is internally consistent. A signature over that root proves *who* attested it, and *when*. PCIS keeps the private signing key **off the machine that runs the substrate**.

The gardener, the tree, and the entire runtime can compute the current root and request a signature over it — but they cannot read or reach the private key. So a compromised substrate cannot forge an attestation over its own state, and cannot silently re-sign a rewritten past: the most it can do is refuse to advance, which is visible, not deniable.

This is the property the tamper-evident ledgers PCIS is measured against do not have. Their signer typically lives beside the log, so a compromised host is a compromised ledger — it can rewrite history and re-sign it in one move. Moving the key off-box splits that into two separate trust domains: integrity of the record, and authority to attest it. It is a boundary, not plumbing — the one line an attacker who owns the box still cannot cross.

## 5. Gap-Scan (Completeness, Not Just Correctness)
Most verification systems ask: is what the agent knows correct? Gap-scan asks a different question: what should the agent know that it doesn't? The scanner reads recent session logs and external inputs, extracts significant facts and decisions, and cross-checks them against the knowledge tree. Entries that are missing — never committed, or committed but since pruned — are staged for addition. Correctness and completeness are orthogonal problems. PCIS solves both.

## 6. Pruning Protocol
A knowledge tree that only grows becomes a liability. PCIS includes a pruning protocol that identifies leaves with low confidence scores, high age relative to their domain, or explicit supersession by newer leaves. Pruning is not deletion — candidates are flagged, reviewed, and removed only when confirmed stale. The goal is a tree that stays sharp: high-signal, low-noise, trustworthy.

## 7. Model-Agnostic Design
PCIS does not depend on any specific language model. The knowledge tree, integrity layer, adversarial pass, and gap-scan all operate through a standard API interface. The underlying model — GPT-4, Claude, Llama, or any locally-hosted model — can be swapped without touching the memory layer. This means no vendor lock-in, no retraining required when models change, and the ability to run entirely on-premises with local models.

## 8. Typed Synapse Graph

`core/knowledge_synapses.py`

Cross-leaf relationships are first-class objects. Each synapse is a directed typed edge between two leaves — SUPPORTS, CONTRADICTS, REFINES, DERIVES_FROM, or SUPERSEDES — stored in `data/synapses.json` and tamper-evident via SHA-256. When the gardener commits a COUNTER leaf, it automatically wires a CONTRADICTS synapse back to the challenged leaf. This turns a flat tree of facts into a network of claims where confidence propagates through evidence chains.

The combined root hash (`sha256(tree_root + synapse_root)`) is computed at boot, ensuring structural integrity across both the knowledge tree and its relationship graph.

## 9. Belief Traversal Engine

`core/belief_traversal.py`

`assess_belief(leaf_id)` walks the synapse graph via BFS, aggregating evidence: supporting leaves boost confidence, contradictions reduce it, depth decay applies per hop. The result is a net confidence score, a stance classification (CONFIDENT / UNCERTAIN / CONTESTED / SUPERSEDED), and a plain-English explanation of why the claim carries that confidence.

`query_belief(text)` accepts a natural-language query, runs semantic search to find the most relevant leaf, then calls `assess_belief` on it. The agent can now answer not just *what a claim says* but *what confidence it carries, and why*.

This is the first step toward Bayesian confidence (a Later roadmap item) — the architecture is in place, the update rule is currently heuristic rather than formally Bayesian.

## PCIS and External Memory Continual Learning

The central challenge in continual learning is the stability-plasticity tradeoff: systems that learn new things tend to forget old ones (catastrophic forgetting), and systems that preserve old knowledge tend to resist new learning. Most approaches address this by modifying training procedures or weight update rules.

PCIS takes a different approach: externalize memory entirely, and manage the stability-plasticity tradeoff at the knowledge layer rather than the weight layer.

The mapping is direct:
- **Replay buffer** → the knowledge tree (prior knowledge is always available, never overwritten by new model updates)
- **Stability** → the adversarial gardener (pressure-testing prevents overconfidence in stale claims)
- **Plasticity** → gap-scan (identifies what's missing, drives targeted knowledge addition)
- **Forgetting** → pruning protocol (explicit, deliberate removal of confirmed-stale leaves)

The result: an agent that accumulates knowledge over time, challenges its own claims, and can prove what it committed to and when — without retraining, without weight updates, and without losing prior context.

## Identity Portability

The Merkle root hash is determined solely by tree content — not by which model processed it. This is an enforced invariant (tested in `tests/test_pcis.py::TestIdentityPortability`): the same knowledge tree produces the same root hash whether the underlying LLM is GPT-4, Claude, Llama, or any other model.

This means the root hash is a model-agnostic identity. An agent can switch underlying models mid-deployment — or run the same tree through multiple models simultaneously — and the cryptographic identity remains unchanged. Memory follows the agent, not the model.

---

## Codebase Reference

### Core Modules

**`core/knowledge_tree.py`** — The foundation. Everything else depends on this. It defines the data model: a tree has branches (e.g. "identity", "lessons", "technical", "relationships"), and each branch holds leaves. Each leaf carries an id, hash, content, source, confidence score, created timestamp, and promoted_to field.

Four critical functions:
- `hash_leaf` — SHA-256 from content + branch + timestamp
- `compute_branch_hash` — builds a binary Merkle tree from sorted leaf hashes with RFC 6962 domain separation (`0x00` leaf / `0x01` node prefixes); odd levels are padded with a zero-hash (`MERKLE_PAD`), **not** duplicated, to prevent CVE-2012-2459 collisions
- `compute_root_hash` — takes all branch hashes, iteratively pairs and hashes upward in a binary tree until one root remains
- `tree_lock()` — context manager wrapping the full read-modify-write cycle under an exclusive file lock: load → mutate → write, all atomic

Two proof functions:
- `generate_proof(tree, branch, leaf_id)` — returns a Merkle inclusion proof (sibling hashes + positions from leaf to branch root)
- `verify_proof(leaf_hash, proof, expected_root)` — standalone verification, no tree access needed

Also provides `add_knowledge` (with input validation), `prune_leaf`, `diff_trees`, and a CLI for `--add`, `--show`, `--prune`, `--diff`, `--export`, `--root`, `--proof`, `--verify-proof`. Tree persists as `data/tree.json`.

---

**`core/verify_memory.py`** — Integrity checking for the codebase itself, not the knowledge tree. Tracks a hardcoded list of core files, hashes each with SHA-256, and computes a Merkle-style root over all of them. On first run (`--init`), writes a manifest to `data/integrity/manifest.json`. On subsequent runs, recomputes all hashes and compares — any change is reported by filename. `--update` accepts the current state as the new baseline. `--status` returns CLEAN/CHANGED/MISSING for scripting. Run this at session start to verify your own code was not modified between sessions.

---

**`core/gardener.py`** — The adversarial maintenance agent. Loads the knowledge tree, formats it as readable text, and sends it to a local LLM (qwen3.5:9b via Ollama) asking it to find echo chambers, generate counter-arguments, identify cross-branch connections, and flag stale leaves. The LLM responds in pipe-delimited format (`COUNTER|branch|content|confidence`, `SYNAPSE|content|confidence`, `FLAG|leaf_id|reason`); staged items are written as JSONL for reliable parsing. If parsing yields zero results, it retries once. That retry fires whenever a whole pass yields zero directives — whether the output was garbled or the model genuinely returned nothing (a small local model comes back empty on some passes). It is distinct from the per-claim case in §1: when a pass raises counters but none target a given claim, that claim simply gets nothing — no counter leaf, no synapse, no confidence change — and no retry. The gardener only ever commits counters it actually parsed; it never injects a synthetic counter to fill an empty result.

Tiered commit system:
- Counter-leaves targeting operational branches (`technical`, `lessons`) → auto-committed
- Counter-leaves targeting constitutional branches (`identity`, `philosophy`, `core`) → staged for human review
- Synapses (cross-branch connections) → always staged

A separate `--gap-scan` mode reads daily memory notes (optional `memory/YYYY-MM-DD.md` files — none exist by default), extracts key facts via LLM, then checks each against the tree via semantic search — anything below similarity 0.6 is flagged as a gap. Output: `gardener-log.md`, `gardener-staging.md`, and a notify flag file. Run on demand, or scheduled as a daily cron job.

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

**`core/adversarial_validator.py`** — External adversarial validation agent. Picks highest-confidence leaves, sends them to an external LLM API for challenge, parses counter-leaves, and saves the full run (with before/after Merkle roots) to JSON. Complements the local gardener: where `gardener.py` is the local maintenance pass you run, `adversarial_validator.py` is the external second opinion — a different model, a different perspective, no shared context with the system it is auditing.

**`demo/demo_tree.json`** — Synthetic knowledge tree: 5 branches, 105 leaves (including 5 seeded COUNTER leaves), zero personal data (enforced by a test). Used to seed `data/tree.json` and drive the demo server.

**`demo/index.html`** — Single-file frontend. Nine tabs (Adversarial first, the default view): Adversarial (counter-leaves with originals), Boot (live Merkle verification), Search (semantic search with hash-pinned results), Knowledge Tree (branch browser), Query (keyword search), Belief (traversal engine — confidence, stance, evidence chain), History (full audit trail), Ingest (add knowledge from text or file), External Validation. Dark theme, vanilla JS, no framework.

---

### Tests (`tests/test_pcis.py`)

Organized into 14 test classes:

| Class | What it verifies |
|-------|-----------------|
| `TestMerkleHashing` | Root hash changes on add/edit, determinism, branch-hash order independence, tamper detection |
| `TestAdversarialCounters` | COUNTER leaf detection, challenged-ID parsing, normal leaves not misidentified |
| `TestDemoTreeIntegrity` | Demo tree schema, confidence ranges, root hash presence, no personal data leakage |
| `TestCrossModuleHashConsistency` | All modules produce identical root, branch, and leaf hashes for the same data |
| `TestAddKnowledgeValidation` | Empty and oversized content rejected with `ValueError` |
| `TestConcurrentSaveTree` | Two threads × 5 writes under `tree_lock()` → exactly 10 leaves, zero data loss |
| `TestIdentityPortability` | Root hash identical across model configs — model-agnostic identity enforced |
| `TestMerkleProofs` | Inclusion proofs: generate, verify, tampered-hash rejection, wrong-root rejection, cross-branch isolation, invalidation on leaf removal, depth = ceil(log₂(n)) |
| `TestBinaryMerkleTreeStructure` | Domain separation (`0x00` leaf / `0x01` node prefixes); odd level padded with `MERKLE_PAD`, not duplicated |
| `TestCounterParsing` | COUNTER content parsing — challenged-ID extraction, prefix handling, backward-compat |
| `TestGardenerDedupGate` | Near-duplicate COUNTER leaves skipped via embedding similarity; embedding-failure fallback |
| `TestVerifyTreeIntegrity` | Content tampering caught even when hash fields are left untouched (re-derives from content) |
| `TestNoDuplicateLeafCollision` | CVE-2012-2459 duplicate-leaf collision is absent (pad, not duplicate) |
| `TestDomainSeparation` | RFC 6962 domain separation: a domain-separated leaf hash ≠ raw SHA-256 of the same content |

Run with: `python -m pytest tests/ -v`

---

### Config & Infrastructure

**`setup.sh`** — Runs `pip install -r requirements.txt`, creates `data/`, copies `demo_tree.json` into it as the starting tree.

**`requirements.txt`** — `flask>=3.0.0` (demo server), `requests>=2.28.0` (outbound HTTP), and `pytest>=7.0` (tests). The knowledge-tree core — hashing, Merkle, vector math — is pure Python standard library; the listed dependencies are for the demo server, HTTP calls, and the test suite.

**`config.example.json`** — Template with `base_dir`, `llm_provider`, `llm_api_key`, `llm_model`, `demo_mode`. Copy to `config.json` before running adversarial validation.

**`.github/workflows/ci.yml`** — GitHub Actions running the full test suite on Python 3.10, 3.11, and 3.12 on every push and PR to `main`.
