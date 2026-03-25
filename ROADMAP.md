# PCIS Roadmap

Honest about what v1.0 is and what comes next.

---

## Why most AI memory architectures fail

Independent analysis of production AI memory systems reveals seven predictable failure modes. Most systems hit them within six months. PCIS was designed around all seven.

| Failure mode | What happens | PCIS response |
|---|---|---|
| **Memory entropy** | Duplicates accumulate, outdated beliefs persist, retrieval returns noise | Gardener prunes stale leaves, gap-scan deduplicates on commit |
| **No belief revision** | Contradicting memories coexist; system reasons from both | COUNTER leaves, adversarial pass, confidence updates on challenge |
| **Summarization collapse** | Recursive compression destroys detail; memory becomes "various topics discussed" | Architecture avoids recursive summarization — one compression layer only |
| **Retrieval bias** | Vector search reinforces popular/recent beliefs regardless of truth | Adversarial pass specifically targets high-confidence echo chambers |
| **Identity fragmentation** | Memory clusters become disconnected; agent contradicts itself across sessions | Cross-branch synapses, single Merkle-verified root |
| **No epistemic hygiene** | Errors accumulate silently; no mechanism to challenge beliefs | Gardener is dedicated epistemic maintenance — this is the entire architecture |
| **Storage cost collapse** | Developers delete memories or hit hard limits; knowledge base destroyed | `knowledge_prune.py` — evidence-based pruning, not size-based deletion |

> *"Memory is not the problem. Epistemology is."*
> — Independent technical review, March 2026

---

## v1.0 (current)

- [x] Persistent knowledge tree — JSON-based, branch/leaf structure
- [x] Merkle integrity verification — SHA-256 root hash, tamper-evident
- [x] Adversarial pass — external LLM challenges high-confidence leaves, generates COUNTER entries
- [x] Gap-scan — reads session logs, finds knowledge not yet committed to tree
- [x] Pruning protocol — flags stale and low-confidence leaves for review
- [x] Cross-branch synapses — gardener detects and logs connections between knowledge domains
- [x] Model-agnostic design — swap LLM without touching memory layer
- [x] Demo UI — five-tab Flask app, runs locally in 60 seconds

---

## v1.1 — Operational hardening

- [ ] Full end-to-end test suite — demo boots and passes all tabs without manual intervention
- [ ] Docker image — `docker run pcis/demo` with no local Python setup
- [ ] Proper Merkle tree — balanced binary tree with branch proofs, not just root hash
- [ ] Semantic search — embedding-based query, not keyword match
- [ ] Config validation — helpful errors when config.json is missing or malformed
- [ ] Belief decay — confidence degrades automatically over time unless reinforced by new evidence

---

## v1.2 — Agent integration

- [ ] LangChain adapter — PCIS as a memory provider for LangChain agents
- [ ] OpenAI function calling integration — agent reads/writes tree via structured API
- [ ] Webhook support — gardener posts summary to Slack/Discord after nightly run
- [ ] Multi-agent shared tree — multiple agents reading from one verified knowledge source
- [ ] Source credibility weights — evidence from peer-reviewed sources weighted differently from LLM-generated claims

---

## v2.0 — Formal epistemics

The v2.0 architecture upgrades PCIS from narrative reasoning to formal epistemic infrastructure.

- [x] **Belief graph traversal** — assess_belief() engine, typed synapse edges, epistemic stance (CONFIDENT/UNCERTAIN/CONTESTED/SUPERSEDED), Merkle-chained. Shipped 2026-03-25.
- [ ] **Bayesian belief updating** — `P(H|E) = P(E|H)P(H)/P(E)`. Confidence updates by formula based on evidence weight, not heuristic judgment
- [ ] **Typed causal edges** — edges carry semantic type (`causes`, `implies`, `depends_on`, `correlates`), enabling forward inference rather than retrieval only
- [ ] **Contradiction resolution engine** — conflicting beliefs trigger investigation agents; probability redistribution is automatic and auditable
- [ ] **Belief version history** — every update, counter-argument, and confidence change is a versioned commit; full epistemic audit trail
- [ ] **Structural reorganization** — periodic graph reclustering as knowledge domains shift; dead branches collapsed, emergent domains surfaced
- [ ] Role-based access to tree branches (read/write/admin)
- [ ] Distributed Merkle tree — multiple nodes, consensus on root hash
- [ ] Compliance export — audit-ready reports from tree history
- [ ] Dashboard — web UI for tree health, adversarial history, pruning log
- [ ] Hosted option — managed PCIS for teams that don't want to self-host

---

## Alternatives and differentiation

There are other AI memory projects. Here is an honest comparison.

| Project | What it does well | What PCIS does differently |
|---|---|---|
| **Memoria** (MatrixOne) | Git-level branching and rollback, hybrid semantic search, broad MCP agent support | No cryptographic proof — audit trail is logs, not a Merkle root. Requires MatrixOne (Chinese company). Cloud option is a data sovereignty issue for enterprise deployments. PCIS is a JSON file on your own infrastructure. |
| **ByteRover** | Consumer-friendly, 30k+ downloads, OpenClaw memory plugin | Consumer market (personal productivity). No tamper evidence, no adversarial belief challenge, no compliance audit trail. |
| **Letta / MemGPT** | Mature, multi-agent, OS-memory model | No epistemic hygiene — memories accumulate without contradiction detection. No cryptographic integrity. |
| **Mem0** | Simple API, easy integration | Retrieval only — no belief revision, no gardener, no proof of what the agent knew and when. |
| **Traditional RAG** | Fast, scalable, well-understood | Retrieves documents. Does not maintain beliefs, does not detect contradictions, does not prove identity. |

**The core distinction:** most AI memory tools solve *retrieval*. PCIS solves *identity* — what an agent believes, how those beliefs have been challenged, and cryptographic proof of the state at any point in time.

For regulated environments (finance, healthcare, compliance) where "the AI said so" is not enough — PCIS is the only architecture that produces an auditable, tamper-evident belief record.

> *Memoria remembers. PCIS proves.*

---

## Known limitations in v1.0

- Merkle integrity is root-hash only (not full branch proofs) — branch proofs are a v1.1 target
- Confidence values are heuristic, not Bayesian — formal updating is a v2.0 target
- Semantic search requires Ollama + `nomic-embed-text`; keyword search is always available as fallback
- Adversarial validator supports Anthropic, OpenAI, GigaChat, and Ollama — cloud LLM options are live; additional providers are v1.1 work
- No authentication on demo server

These are real gaps. If any of them block you — open an issue.

---

*The still point of the turning model — just needs the turning mechanism to be fully functional.*
