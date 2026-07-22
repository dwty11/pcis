# PCIS Roadmap

Honest about what v1.0 is and what comes next.

---

## Three positions

PCIS is one substrate that sells into three distinct audiences via three distinct framings.

- **Position A — Multi-agent coordination.** Between agents that exchange signed transcripts, a lie by one is detectable by the other with math — no trusted third party needed in that exchange. Demonstrated in a prior release; a multi-agent demo returns after the witness-layer redesign. (Narrower than equivocation-proofness: a dishonest operator can still maintain two trees — see Limitations.)
- **Position B — Single-agent compliance.** Every commitment an AI makes carries an audit trail that survives discovery, replay, and dispute. Shown in the Advocate Demo (Demo 1, below).
- **Position C — Identity continuity.** Your AI's identity survives the model swap. The pianist changes; the song does not. Future demo (Pianist Swap).

---

## Why most AI memory architectures fail

PCIS is designed around seven recurring failure modes of production AI memory systems — the seven in the table below.

| Failure mode | What happens | PCIS response |
|---|---|---|
| **Memory entropy** | Duplicates accumulate, outdated claims persist, retrieval returns noise | Gardener prunes stale leaves; near-duplicate counters are rejected at commit by a semantic dedup gate |
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

## Roadmap and boundaries

Three buckets, so a reader can tell which gaps are on the path and which are architectural boundaries that belong to other layers.

**The floor these gaps sit on — shipped and proven today:** the record is tamper-evident end to end (a SHA-256 Merkle root re-derived from leaf content on every verify, so any edit shows), the gardener adversarially challenges the highest-confidence claims, and the root is signed by an **off-machine** key a compromised host cannot forge. Everything below is what is *not* yet done; none of it subtracts from that floor.

### Next — named, shaped, intended

- **Output grounding.** Nothing proves an answer came from the tree; the agent volunteers what it used. The record shows what was committed, not what a given response actually drew on.
  - *Verified retrieval trace (concrete sub-step).* Log which leaves were injected into the prompt, with content hashes, and re-verify each against the tree at read time — `resolves` / `drifted` / `gone`. This proves **retrieval provenance, not answer provenance**: that certain leaves were fed in and still match the tree, not that the answer used them. Answer provenance — proving a generation actually *used* an injected leaf rather than merely being shown it — is **not closable from PCIS's layer at all**: whether a model's output drew on a given input lives in model internals (interpretability and attribution), not in a memory substrate. No roadmap item below closes it, and none should be waited for — it belongs with the **Not ours** boundaries. The retrieval trace closes retrieval provenance, which is the part this layer *can* prove.
- **Ingestion.** Claims enter through `pcis add` / the CLI; nothing reads an agent's output stream and commits what it asserted.
- **Third-party agent integration.** The plugin and skills interfaces are built and working — an agent runs on them today. What's missing is not code but *independent* evidence: no agent built by a third party has integrated against them yet. The interfaces are done; outside validation is the gap.

### Later — real, but further out

- **External witness layer.** Closes *equivocation* — a dishonest operator maintaining two trees and showing different versions to different parties, each verifying under the same key. The off-machine signing key already covers a compromised host; an independent witness is the separate layer that catches a two-faced operator.
- **Multi-agent enforcement.** The documentation describes cross-agent checks the code stages but does not enforce.
- **Bayesian confidence.** Confidence updated by formula from evidence weight, in place of today's heuristic values.

### Not ours — architectural boundaries belonging to other layers

Named so the scope stays honest, not claimed:

- **Identity binding** — tying the record to a real-world or hardware identity is the domain of PKI, DIDs, and runtime attestation (TPM / TEE).
- **State commitment** — committing to current external state, rather than the history-shaped attestation log PCIS is, belongs to consensus and ledger systems (blockchains, state channels, timestamping authorities).
- **Forward secrecy** — protecting past records against a future key compromise is a key-agreement / transport property (ephemeral-key protocols like TLS 1.3 or the Signal ratchet), not something a signed at-rest log provides.

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

These prove the log wasn't edited. Most of them don't test whether the claim still holds — an intact record and a stale belief coexist just fine. That gap is what PCIS is built for.

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

- Confidence values are heuristic, not Bayesian — formal updating is a Later item (Bayesian confidence, above).
- **Belief-state ownership is unreconciled — a challenged claim carries two confidence numbers.** The *stored* value on the leaf and the *net-under-challenge* value that belief traversal computes at read time can differ, and nothing designates one as authoritative. On the paths a user actually drives — the gardener's commit and `pcis link` — the stored value is never mutated, so only the read-time net reflects a challenge (this is by design). The stored value is rewritten only by two internal paths, neither on the CLI: passing `tree=` to `add_synapse` (a direct Python API call) and the batch `recompute_all` (exposed on the demo server's `/api/belief/recompute` endpoint). Both currently *double-count* — they scale the stored value down for a contradiction, and belief traversal then subtracts the same contradiction again at read time. Reconciling which number owns "the belief" is a Later item, tied to Bayesian confidence above.
- Semantic search requires Ollama + `nomic-embed-text`; keyword search is always available as fallback.
- Adversarial validator supports Anthropic, OpenAI, Ollama, and any OpenAI-compatible local adapter. Additional cloud providers can be added by extending the validator config.
- No authentication on the demo server — demo is intended for local use only.

These are real gaps. If any of them block you — open an issue.

---

*The still point of the turning model — just needs the turning mechanism to be fully functional.*
