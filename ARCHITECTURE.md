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
