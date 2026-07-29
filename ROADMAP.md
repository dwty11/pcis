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
- [x] Model-agnostic design — swap LLM without touching memory layer ([amended](#amendment--model-agnosticism): the *memory* is model-agnostic; cognition is not)
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

## Amendment — model-agnosticism

Previously stated without qualification. Corrected:

> **Model-agnostic memory. Model-inflected cognition.**

The substrate is portable. The Merkle root is a pure function of tree content — model configuration is not an input to the hash pipeline, enforced by test. The same cryptographic primitives are byte-identical in two independent codebases — verified by a committed test that compares the source of four primitives (`hash_leaf`, `_merkle_tree_from_hashes`, `compute_branch_hash`, `generate_proof`) and the `MERKLE_PAD` constant across both, and which runs only where both codebases are present and skips otherwise.

What does **not** hold is behavioural invariance. A different model over an identical tree retrieves differently, synthesises differently, and produces a differently-behaving agent. At small scale the difference is cosmetic. At retrieval scale it is load-bearing, because what the system *appears to know* becomes a function of what the model chose to fetch.

The pianist changes and the score does not — but the performance is the pianist's. What survives a model swap is the record. A bad pianist is reversible today; **detectable** once run provenance lands, since the current artifacts cannot distinguish a degraded run from a clean one.

---

## Roadmap and boundaries

Three buckets, so a reader can tell which gaps are on the path and which are architectural boundaries that belong to other layers.

**The floor these gaps sit on — shipped and proven today:** the record is tamper-evident end to end (a SHA-256 Merkle root re-derived from leaf content on every verify, so any edit shows), the gardener adversarially challenges the highest-confidence claims, and the Merkle root is signed with an Ed25519 key whose signature is verified against a **pinned** public-key fingerprint (no embedded-key trust). Holding that key off the machine — so a compromised host cannot forge the root — is a supported deployment pattern via the API, **not the default** ([Signing](docs/SIGNING.md)). Everything below is what is *not* yet done; none of it subtracts from that floor.

### Next — named, shaped, intended

- **Run provenance.** An artifact describing a run records what happened, not what was attempted. A producer can write a report naming *configuration* rather than *outcome* — the model it was configured to call rather than the one that answered, a commit that was intended rather than one that landed, a status derived from a reason table rather than from a response. The report then reads as evidence of the run it describes, and nothing distinguishes it from one that is.

  The rule is derived, not narrated: **a field naming a state must be computed from an observation of that state.** `tree_written` is a digest of the tree file before and after the run, not a literal. A root naming a post-state is emitted only when a write occurred; otherwise the projection ships under a name that says it is one — `merkle_root_projected`, not `merkle_root_after`. A verdict distinguishes "the check ran and returned nothing" from "the check did not run," because a bare absence reads as the first and is often the second.

  This is adjacent to output grounding rather than inside it. Output grounding asks what a retrieval was *based on*. Run provenance asks what a producer actually *did*. The two share a discipline: the claim and the computation have to be the same object, not two objects that are supposed to agree.

  - *Sub-step, concrete.* The adversarial validator's run artifact already records per-call outcomes — `attempts[]` carries each call's outcome and its error, and aggregate counts are derived from that set, so a run where four calls answered and one failed is distinguishable from a clean one. What remains is provenance of the responder itself: provider and model are still taken from configuration rather than read back from the response, and the artifact records neither the resolved path of the tree it opened nor each call's finish reason.

  **Fields and their derivation sites.**

  *Shipped:* `tree_written`, `merkle_root_before`, `merkle_root_after` | `merkle_root_projected`, `attempts[].outcome`, `attempts[].error`, `counters[].produced_by`.

  *Outstanding:* `tree_path`; and three fields blocked on the same boundary — the provider functions return response *text* rather than the response, so nothing response-derived can be populated until that return type changes:

  | Field | Derived from |
  |---|---|
  | `provider` | the dispatch branch that answered — the endpoint actually called, not the response |
  | `model` | the response |
  | `attempts[].finish_reason` | the response's stop reason, normalised across providers |

  Aggregates — `entries_challenged`, `branches_visited`, counter counts — are computed at serialization time from `attempts[]`, not written alongside it.

  Exempt as configuration: `run_date`. Two further configuration fields — `branches_targeted` and `max_tokens` — are not yet emitted; when they are, they are exempt only once `branches_visited` and `attempts[].finish_reason` record what actually happened.

  **Shipped when:** the outstanding fields above each have a derivation site in code; aggregates are computed from `attempts[]` at serialization rather than written alongside it, so a clean-looking summary over a mixed run is unwriteable; and a producer that cannot derive a field emits a tagged absence — `{"observed": false}` or `{"observed": true, "value": X}` — rather than a plausible value.
- **Ingestion.** Claims enter through `pcis add` / the CLI; nothing reads an agent's output stream and commits what it asserted.
- **Third-party agent integration.** The plugin and skills interfaces are built and working — an agent runs on them today. What's missing is not code but *independent* evidence: no agent built by a third party has integrated against them yet. The interfaces are done; outside validation is the gap.

### Shipped — previously in Next

- **Output grounding — verified retrieval trace.** Live on five retrieval paths: the demo server's `query`, `search`, and `run-validation` routes; `pcis search`; and the agent plugin's search. Injected leaf IDs are logged with content hashes and re-verified against the tree at read time: `resolves` / `drifted` / `gone` / `withdrawn`.

  The rule that made it honest: **a detected difference is always evidence; only a pass needs attestability.** A mismatch proves the comparison *could* fail — it just did. A pass proves nothing unless the check had the capacity to fail. So a trace whose content was drawn from the tree, re-verified against a tree that has not changed since, renders **no verdict at all**: that comparison compares a value to itself and is structurally incapable of failing. The record says so rather than showing green.

  Each leaf's current content is hashed and compared directly against the hash recorded at retrieval time. The per-leaf comparison never consults the Merkle root — the root is used only to decide whether a *passing* result can be attested, never to suppress a detected difference. A leaf whose content is edited and whose own hash field is recomputed leaves the Merkle root byte-identical, and an earlier trace still reports it as `drifted`.

  What this does not close is unchanged. It proves **retrieval provenance, not answer provenance** — that certain leaves were fed in and still match the tree, not that the answer used them. Answer provenance is not closable from this layer and remains under **Not ours**.

### Later — real, but further out

- **External witness layer.** Closes *equivocation* — a dishonest operator maintaining two trees and showing different versions to different parties, each verifying under the same key. A signing key held off the machine (a supported deployment pattern) covers a *compromised host*; an independent witness is the separate layer that catches a *two-faced operator*.
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
