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
