# PCIS Roadmap

Honest about what v1.0 is and what comes next.

---

## Three positions

PCIS is one substrate that sells into three distinct audiences via three distinct framings.

- **Position A — Multi-agent coordination.** Between agents that exchange signed transcripts, a lie by one is detectable by the other with math — no trusted third party needed in that exchange. Demonstrated in a prior release; a multi-agent demo returns after the witness-layer redesign. (Narrower than equivocation-proofness: a dishonest operator can still maintain two trees — see Limitations.)
- **Position B — Single-agent compliance.** Every commitment an AI makes carries an audit trail that survives discovery, replay, and dispute. Future demo.
- **Position C — Identity continuity.** Your AI's identity survives the model swap. The pianist changes; the song does not. Future demo (Pianist Swap).

---

## Why most AI memory architectures fail

PCIS is designed around seven recurring failure modes of production AI memory systems — the seven in the table below.

| Failure mode | What happens | PCIS response |
|---|---|---|
| **Memory entropy** | Duplicates accumulate, outdated claims persist, retrieval returns noise | Gardener prunes stale leaves, gap-scan deduplicates on commit |
| **No claim revision** | Contradicting memories coexist; system reasons from both | COUNTER leaves and a CONTRADICTS synapse from the adversarial pass; belief traversal then reports a lower net-under-challenge confidence at read time and surfaces the contradiction for review — the stored value is left intact, not silently overwritten |
| **Summarization collapse** | Recursive compression destroys detail; memory becomes "various topics discussed" | Architecture avoids recursive summarization — one compression layer only |
| **Retrieval bias** | Vector search reinforces popular/recent claims regardless of truth | Adversarial pass specifically targets high-confidence echo chambers |
| **Identity fragmentation** | Memory clusters become disconnected; agent contradicts itself across sessions | Cross-branch synapses, single Merkle-verified root |
| **No epistemic hygiene** | Errors accumulate silently; no mechanism to challenge claims | Gardener is dedicated epistemic maintenance — this is the entire architecture |
| **Storage cost collapse** | Developers delete memories or hit hard limits; knowledge base destroyed | `knowledge_prune.py` — evidence-based pruning, not size-based deletion |

> *"Memory is not the problem. Epistemology is."*

---

## v1.4.1 (current)

- [x] Persistent knowledge tree — JSON-based, branch/leaf structure
- [x] Merkle integrity verification — SHA-256 root hash, tamper-evident
- [x] Adversarial pass — the gardener challenges high-confidence leaves on a local model, generates COUNTER entries
- [x] Gap-scan — reads session logs, finds knowledge not yet committed to tree
- [x] Pruning protocol — flags stale and low-confidence leaves for review
- [x] Cross-branch synapses — typed edges (SUPPORTS / CONTRADICTS / REFINES / DERIVES_FROM / SUPERSEDES), Merkle-chained
- [x] Belief traversal — BFS confidence assessment, stance classification (CONFIDENT / UNCERTAIN / CONTESTED / SUPERSEDED), plain-English reasoning
- [x] Semantic search — embedding-based query via Ollama + nomic-embed-text, keyword fallback when unavailable
- [x] Model-agnostic design — swap LLM without touching memory layer
- [x] Belief version history — append-only log of every confidence change, counter-argument, and update; full audit trail via belief_history.py
- [x] Demo UI — nine-tab Flask app, runs locally in 60 seconds

---

## Demo 1 — The Advocate Demo

A CLI proof-of-concept for single-agent compliance and self-challenge (Position B). A legal-assistant agent holds a fabricated case citation at 0.95 confidence; the gardener — not told which leaf to attack — challenges it against the record's own verification note. Its confidence moves under challenge and the counter is surfaced for review, permanently on the record. Runs in under 60 seconds.

```bash
cd demo/advocate-demo
./run_demo.sh                 # replay a locked, recorded real gardener run
./run_demo.sh --live          # run the gardener fresh on your own local model
./run_demo.sh --verify-self   # SHA-256 every script + fixture vs the canonical fingerprint
```

See: [`demo/advocate-demo/README.md`](demo/advocate-demo/README.md)

---

## Already shipped in 1.x

- [x] Docker image — `docker compose up` with no local Python setup
- [x] Proper Merkle tree — binary tree with inclusion proofs (`generate_proof` / `verify_proof`), `--proof` and `--verify-proof` CLI commands
- [x] Belief decay — exponential decay (half-life 180 days), constraints/state branches exempt, CLI `--decay [--dry-run]`
- [x] Ed25519 root signing — signs the Merkle root with an operator-controlled key (`pcis sign init/root/verify/pubkey`)

## v2.0 — what's next

- [ ] **External root anchoring** — optionally post signed root hashes to a Sigstore-compatible transparency log on a schedule. Closes the gap between tamper-detection (current) and tamper-evidence against a privileged attacker.
- [ ] **Bayesian belief updating** — `P(H|E) = P(E|H)P(H)/P(E)`. Confidence updates by formula based on evidence weight, not heuristic judgment.
- [ ] **Typed causal edges** — edges carry semantic type (`causes`, `implies`, `depends_on`, `correlates`), enabling forward inference rather than retrieval only.
- [ ] **Contradiction resolution engine** — conflicting claims trigger investigation; probability redistribution is automatic and auditable.
- [ ] **Structural reorganization** — periodic graph reclustering as knowledge domains shift; dead branches collapsed, emergent domains surfaced.
- [ ] Full end-to-end test suite — demo boots and passes all tabs without manual intervention.
- [ ] Config validation — helpful errors when config.json is missing or malformed.
- [ ] LangChain adapter — PCIS as a memory provider for LangChain agents.
- [ ] OpenAI function calling integration — agent reads/writes tree via structured API.
- [ ] Webhook support — gardener posts summary after nightly run.
- [ ] Multi-agent shared tree — multiple agents reading from one verified knowledge source.
- [ ] Source credibility weights — evidence from peer-reviewed sources weighted differently from LLM-generated claims.
- [ ] Role-based access to tree branches (read/write/admin).
- [ ] Distributed Merkle tree — multiple nodes, consensus on root hash.
- [ ] Compliance export — audit-ready reports from tree history.
- [ ] Dashboard — web UI for tree health, adversarial history, pruning log.
- [ ] Hosted option — managed PCIS for teams that don't want to self-host.

---

## Alternatives and differentiation

PCIS competes on two fronts, and the differentiator is different on each:

### vs. AI memory tools — wedge: a verifiable, challenged record

| Project | What it does well | What PCIS adds |
|---|---|---|
| **Memoria** (MatrixOne) | Git-level branching and rollback, hybrid semantic search, broad MCP agent support | A tamper-evident Merkle record plus an adversarial pass; runs as a local JSON file, not cloud-coupled by default. |
| **ByteRover** | Consumer-friendly, 30k+ downloads, agent memory plugin | Tamper evidence, adversarial claim-challenge, and a compliance audit trail. |
| **Letta / MemGPT** | Mature, multi-agent, OS-memory model | Contradiction detection and epistemic hygiene; cryptographic integrity over every state. |
| **Mem0** | Simple API, easy integration | Claim revision (the gardener) and proof of what the agent knew, and when. |
| **Traditional RAG** | Fast, scalable, well-understood | A challenged claim record with contradiction detection — retrieval alone maintains none. |

### vs. tamper-evident / audit ledgers — wedge: the self-challenge

These prove the log wasn't edited. None of them test whether the claim still holds — an intact record and a stale belief coexist just fine. That gap is what PCIS is built for.

| Project | What it does well | What PCIS adds |
|---|---|---|
| **ChainProof** | Hash-chained, tamper-evident audit log | An adversarial process that attacks the record's own high-confidence claims. |
| **SignLedger** | Signed, append-only ledger | Contradiction detection and COUNTER entries — proof-of-intact is not proof-of-correct. |
| **Capsule Protocol** | Cryptographic commitment of records | Self-challenge over the committed claims, not just proof they're unchanged. |
| **Signatrust** | Signature-based integrity attestation | Epistemic maintenance: the gardener pressure-tests what was attested. |
| **VCP** | Verifiable claim / credential proofs | Ongoing adversarial re-challenge, not one-time verification. |

**The core distinction:** most AI memory tools solve *retrieval*; audit ledgers solve *tamper-evidence*. PCIS pairs a tamper-evident claim record with an adversarial process that challenges the agent's own high-confidence claims — and **the self-challenge, not the tamper-evidence, is the wedge**. Tamper-evident append-only records are well-established (Certificate Transparency, Sigstore/Rekor, hash-chained logs); a substrate that attacks its own record for contradictions and staleness is the novel part.

---

## Known limitations

- Confidence values are heuristic, not Bayesian — formal updating is a v2.0 target.
- **Belief-state ownership is unreconciled — a challenged claim carries two confidence numbers.** The *stored* value on the leaf and the *net-under-challenge* value that belief traversal computes at read time can differ, and nothing designates one as authoritative. On the paths a user actually drives — the gardener's commit and `pcis link` — the stored value is never mutated, so only the read-time net reflects a challenge (this is by design). The stored value is rewritten only by two internal paths, neither on the CLI: passing `tree=` to `add_synapse` (a direct Python API call) and the batch `recompute_all` (exposed on the demo server's `/api/belief/recompute` endpoint). Both currently *double-count* — they scale the stored value down for a contradiction, and belief traversal then subtracts the same contradiction again at read time. Reconciling which number owns "the belief" is a v2.0 target, tied to Bayesian belief updating above.
- Semantic search requires Ollama + `nomic-embed-text`; keyword search is always available as fallback.
- Adversarial validator supports Anthropic, OpenAI, Ollama, and any OpenAI-compatible local adapter. Additional cloud providers can be added by extending the validator config.
- No authentication on the demo server — demo is intended for local use only.

These are real gaps. If any of them block you — open an issue.

---

*The still point of the turning model — just needs the turning mechanism to be fully functional.*
