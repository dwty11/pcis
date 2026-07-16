# PCIS — Persistent Cognitive Integrity System
### What did your agent commit to, and when? And can you prove no one changed the record?

Like the amnesiac in *Memento*, an AI agent runs on a memory it can't vouch for — a record it might have edited yesterday, quietly gone stale, or turned self-contradictory, with nothing checking. PCIS makes that record tamper-evident and self-challenging: what the agent committed to can be *checked*, not just trusted.

An AI agent makes a call: approves the transaction, gives the advice, takes the action. Later a regulator, an auditor, or a customer's lawyer asks *why — and what did it know at the time?* (SR 11-7, adverse-action, GDPR Art. 22, the EU AI Act — the questions are already on the exam.) Today the only answer is a log you could have edited yesterday, sitting on a memory that has been quietly accumulating contradictions no one caught. There's nothing to trust the record with — and nothing watching the agent as its own claims drift, conflict, or go stale.

PCIS (Persistent Cognitive Integrity System) closes that gap. It gives an agent a claim record that is **self-challenging** and **tamper-evident**. An adversarial process attacks the agent's high-confidence claims, hunting contradictions and weak reasoning. Challenges it can't answer without contradicting an existing entry become permanent COUNTER entries, confidence propagates downstream, and nothing is ever overwritten — and the whole record can be proven unaltered. So when someone asks *what did this agent commit to when it made that call*, you have an answer that survives the question.

> **RAG retrieves. PCIS proves.**
> **Memory is not the problem. Epistemology is.**

**The full argument:** [Persistent Cognitive Integrity — the case](docs/PCIS.md). The README is the front door; the essay is the *why*.

> **Status — the mechanism vs. a service.** The self-challenging gardener is a **capability you run**, not a background service: give it a local Ollama model or an LLM API key and it attacks your tree's high-confidence claims and appends real, append-only COUNTER entries. Nothing runs nightly on its own — you invoke it, or schedule it as a cron job (see **Run Gardener**, below). **What ships and runs with zero setup is the demo:** `PCIS_BASE_DIR=. python3 core/gardener.py --demo` (no LLM) prints the Merkle root before and after a synthetic COUNTER is written; and the packaged **Liar's Demo** — a locally verifiable run over locked canonical fixtures (the live conversation runner is stubbed in v1) — catches an agent misrepresenting what it said or remembered, its `verify_room.py` returning CLEAN / REFUTED / INCONCLUSIVE, reproducible offline by anyone. The COUNTER entries in the demo's **Adversarial** tab are shipped demo content — run the gardener on your own tree to write your own.

**What PCIS is *not*.** Not a blockchain. Yes, the record is append-only and hash-linked — that part is mundane and solved. The difference: a blockchain immortalizes data it never questions; PCIS spends its compute attacking its own. No chain, no consensus, no token, no network; just one agent, locally verifiable. Not a vector database — it doesn't merely store and return what it holds; it *challenges* it. The cryptography (a Merkle-hashed tree, SHA-256 root) is *how* the record stays honest: plumbing, not the pitch.

PCIS is a **layer**, not a platform: it wraps your agent's memory and decision calls and sits alongside your identity and attestation stack (PKI, DIDs, runtime attestation), proving what a given agent asserted at a given moment — not replacing any of them.

> **On governance:** the gardener changes the *record*, not the agent. It appends adversarial challenges and confidence metadata (append-only — nothing is overwritten or deleted; synapses and constitutional counters are staged for human review). No weights, code, tools, or decision rules are modified.

[![CI](https://github.com/dwty11/pcis/actions/workflows/ci.yml/badge.svg)](https://github.com/dwty11/pcis/actions/workflows/ci.yml) [![License: BSL 1.1](https://img.shields.io/badge/License-BSL_1.1-orange)](https://github.com/dwty11/pcis/blob/main/LICENSE) [![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/) [![Version](https://img.shields.io/badge/version-1.4.1-green)](https://github.com/dwty11/pcis/releases) [![Last Commit](https://img.shields.io/github/last-commit/dwty11/pcis)](https://github.com/dwty11/pcis/commits/main)

---

Built by [@dwty_11](https://x.com/dwty_11)

---

## Self-Improving Knowledge Loop

PCIS doesn't just store knowledge — it challenges it. Four components you run on a maintenance pass (a nightly cron is the recommended cadence) keep the tree honest. The **Adversarial Gardener**, when you run it, uses an external LLM to challenge high-confidence claims, searching for contradictions and weak reasoning; when a challenge holds, a COUNTER leaf enters the tree and confidence updates propagate. The **Gap-scan** reads session logs, extracts significant facts and decisions, and cross-checks them against the existing tree — anything missing is staged for addition. **Belief Decay** degrades confidence on stale leaves over time, so the tree stays sharp, not just big. And the **External Validator** — a second LLM, running outside the system with no shared context — audits the tree independently, catching blind spots the gardener can't see from inside.

Other systems claim learning loops. The difference here: every change — every counter-leaf, every confidence adjustment, every decay event — is Merkle-hashed and logged. Root signing (Ed25519 over the Merkle root) ships today; *external* anchoring — posting that signed root to a public transparency log — is on the v2.0 roadmap.

The adversarial gardener and external validator need a local Ollama model or an LLM API key. The fully reproducible, zero-external-call proof is the **Liar's Demo** below.

---

## See it in action

PCIS comes with two demos:

**Nine-tab web demo** — run `bash start_demo.sh` from the repo root. Opens at `localhost:5555`. Shows the full architecture: Merkle integrity, knowledge tree, query, adversarial gardener, external validation.

**The Liar's Demo** — a CLI proof-of-concept demonstrating tamper-evident agent memory. Two AI agents converse; one later claims it said something different. The math catches the lie — verifiably, offline, in one command. (v1 replays six locked canonical runs; the live conversation runner is stubbed and lands in v1.1.) Run it:

```bash
cd demo/liars-demo
pip3 install -r requirements.txt
./run_demo.sh --verify-self      # confirm script + fixture fingerprint
./run_demo.sh --text-only        # REFUTED — text substitution caught
```

See: [`demo/liars-demo/README.md`](demo/liars-demo/README.md)

---

## Try it in 60 seconds

```bash
git clone https://github.com/dwty11/pcis.git
cd pcis
bash setup.sh
bash start_demo.sh
```

Open `http://localhost:5555` — nine tabs showing the full architecture live.

---

## Make It Yours in 5 Minutes

The demo runs on synthetic data. Here's how to build a real knowledge tree.

**Add knowledge:**

```bash
python3 core/knowledge_tree.py --add technical "Our API timeout is 30 seconds" --confidence 0.85
python3 core/knowledge_tree.py --add lessons "Never deploy on Fridays" --confidence 0.95 --source "postmortem-2026-01"
python3 core/knowledge_tree.py --add technical "Postgres performs better than MySQL for our workload" --confidence 0.7
```

**See your tree:**

```bash
python3 core/knowledge_tree.py --show
```

**Print the Merkle root** — a compact fingerprint of the whole tree (the per-leaf content tamper check is below):

```bash
python3 core/knowledge_tree.py --root
```

**Search by meaning** (requires [Ollama](https://ollama.com) + `ollama pull nomic-embed-text`):

```bash
python3 core/knowledge_search.py --reindex
python3 core/knowledge_search.py "what do we know about performance?"
```

**Challenge your own claims:**

```bash
PCIS_BASE_DIR=. python3 core/gardener.py --dry-run
```

The gardener reads your tree, finds overconfident leaves, and generates counter-arguments. `--dry-run` shows what it would do without writing anything. (The gardener refuses to run without `PCIS_BASE_DIR` — a deliberate safety check; see [Operational Safety](#operational-safety).)

**Prove tamper detection works — one command:**

```bash
bash setup.sh     # one-time: initialize data/tree.json
./verify.sh       # re-derives every leaf hash, recomputes the root, reports the status
```

Open `data/tree.json` and change one character in any leaf. Run `./verify.sh` again — the status flips to `✗ TAMPERED` and names the leaf. Undo the change; it's `✓ Untampered` again. That's Merkle integrity: the check re-derives every hash **from content**, so one silently changed byte can't hide.

---

## What PCIS Does

PCIS is an **accountability substrate** for AI agents: it holds an agent's claims as a record that is *self-challenging* and *tamper-evident*, so what the agent committed to — and when — can be proven after the fact.

The record persists across sessions, yes — but persistence (memory) is table stakes. The point is what sits on top of it. Every claim carries its source and confidence; an adversarial process attacks the high-confidence ones, and challenges that hold become permanent COUNTER entries — nothing is overwritten. A Merkle root (SHA-256) over every leaf detects any modification, including silent ones. So the agent doesn't just remember: it can show *why* it asserted a claim, the record shows how that claim held up under challenge, and the whole thing can be proven unaltered.

PCIS sits beneath the orchestration layer and beneath the LLM, and it is **model-agnostic** — GPT, Claude, Llama, or a local model; switching the model touches nothing in the integrity layer.

For the full architecture: [ARCHITECTURE.md](ARCHITECTURE.md)

---

## What PCIS Does NOT Do

PCIS is one slice of the agent-audit problem — the provable-claim / accountability slice. Other slices live elsewhere, and PCIS does not claim to solve them.

- **Not a replacement for identity binding.** PCIS proves that a given keypair committed a given claim at a given time. Binding that keypair to a real-world organization, person, or accredited operator is the job of PKI, DIDs, or runtime attestation. Out-of-band trust establishment sits on top.
- **Not a guarantee that the agent's output reflects the tree.** The signature proves the agent committed to assertion A at logical time T. Whether the message that followed was actually derived from A is testimony, not proof of internal causation. A pristine tree and a hallucination can coexist; PCIS catches the second only insofar as the answer contradicts a leaf the agent claimed to hold.
- **Not equivocation-proof on its own.** A dishonest operator can in principle maintain two trees and show different versions to different parties — both verify against signed roots from the same key. Closing this gap requires an independent witness layer (third-party co-signer of every committed root) — a separate component, not part of PCIS proper. A runnable **demo** witness ships with the Liar's Demo (`demo/liars-demo/start_witness.sh`): it independently Ed25519-verifies each committed root and hash-chains its observations, so you can watch the mechanism work locally. It is a demonstration stand-in — the production independent-witness is not in this repo.
- **Not a state commitment.** The tree is an *attestation log* — history-shaped. To find an agent's current view of a topic, walk the leaves applying supersedes-resolution and confidence rules. A true sparse-Merkle state commitment is a larger, separate project. PCIS is the honest version of what the underlying tree actually proves.
- **No forward secrecy.** A compromised private key allows backdating signed messages. Key rotation must be operator-driven; old observations remain verifiable under old keys (CT-log model).

These limits are deliberate. Identity-binding, witnessing/equivocation-detection, output-grounding, and state (vs history) commitments each belong in separate layers.

---

## PCIS as External Memory Continual Learning (EMCL)

*A note for ML readers — memory externalization is the commodity substrate here; the wedge is still the self-challenging gardener. This is just how that substrate maps onto continual-learning.*

Updating model weights directly to learn over time causes catastrophic forgetting — new knowledge overwrites old. PCIS sidesteps it by keeping knowledge outside the weights, in a structured, verifiable tree, with the adversarial gardener (PCIS's wedge) supplying the stability pressure:

- The **knowledge tree** functions as a replay buffer — prior knowledge is never overwritten, only extended or challenged
- The **adversarial gardener** applies stability pressure — high-confidence claims are challenged on each maintenance pass you run, preventing overfit to recent context
- The **gap-scan** drives plasticity — it identifies what the agent should know but doesn't, targeting learning where it's needed
- The **soft-prune protocol** manages forgetting deliberately — stale knowledge is marked pruned without erasing the Merkle record of its existence; the tree stays sharp for active operations while audit queries remain complete

This architecture maps directly onto the stability-plasticity tradeoff that makes continual learning hard. The difference: PCIS does it at the knowledge layer, without touching model weights, and with a Merkle root that detects any modification to every state.

---

## What's in the box

1. **Adversarial Gardener** — an external LLM attacks high-confidence claims and writes COUNTER leaves: the self-challenge that is the point
2. **Merkle Integrity** — tamper-detectable record of what the agent committed to and when (SHA-256 root over every leaf)
3. **Persistent Knowledge Tree** — the structured substrate the gardener runs on; survives session restarts
4. **Gap-Scan** — finds what the agent *doesn't* know, not just what's wrong
5. **Soft-Prune Protocol** — stale leaves are marked pruned without erasing the Merkle record; active operations stay sharp, audit queries stay complete
6. **Model-Agnostic** — swap the LLM without touching the integrity layer

---

## Demo Tabs

| Tab | What it shows |
|-----|---------------|
| **Boot** | Live Merkle root computation — pass or fail, computed in real time |
| **Search** | Semantic search across verified leaves — results pinned to SHA-256 hashes |
| **Knowledge Tree** | Browse the verified knowledge structure, branch by branch |
| **Query** | Ask questions — answers grounded in specific verified leaves |
| **Belief** | Belief traversal — confidence score, stance classification, evidence chain |
| **Adversarial** | Counter-leaves generated automatically by challenging high-confidence entries |
| **History** | Full audit trail — every confidence update, counter-argument, and decay event |
| **Ingest** | Add new knowledge to the tree from text or file |
| **External Validation** | External LLM validation run with before/after Merkle roots |

The demo runs on `demo_tree.json` — a clean synthetic knowledge base, zero personal data.

---

## Prerequisites

- Python 3.10+ (Linux or macOS — Windows not currently supported due to `fcntl` dependency)
- pip

**For the adversarial gardener (recommended):**
- [Ollama](https://ollama.com) running locally
- A model pulled: `ollama pull qwen3:14b` (or any compatible model)
- An LLM API key (Anthropic or OpenAI) — optional; Ollama is the default

**For semantic search:**
- Ollama + `ollama pull nomic-embed-text`
- Without it, search falls back to keyword matching (still functional)

**Demo mode** works without any of the above — synthetic data, no external calls.

---

## Run Gardener (Nightly Maintenance)

```bash
PCIS_BASE_DIR=/path/to/your/data python core/gardener.py
```

Runs: adversarial pass + gap-scan + pruning review. Recommended as a nightly cron job.

---

## Run Adversarial Validation

```bash
python core/adversarial_validator.py
```

The validator supports four providers — set `llm_provider` in `config.json`:

| Provider | `llm_provider` | API key |
|----------|---------------|---------|
| Anthropic | `"anthropic"` | `llm_api_key` in config.json or `ANTHROPIC_API_KEY` env var |
| OpenAI | `"openai"` | `llm_api_key` in config.json or `OPENAI_API_KEY` env var |
| OpenAI-compatible local adapter | `"openai_compat"` | `OPENAI_COMPAT_KEY` env var — points at a local adapter (default `http://localhost:7860`) implementing the OpenAI chat-completions interface |
| Ollama (local, default) | `"ollama"` | No key required — runs against `http://localhost:11434` |

If no provider is configured, defaults to Ollama. Falls back to pre-generated challenges if no API key is found.

---

## Configuration

Copy `config.example.json` to `config.json` and edit — optional, since the gardener and validator default to Ollama with no config:

```json
{
  "base_dir": ".",
  "llm_provider": "anthropic",
  "llm_api_key": "your-key-here",
  "llm_model": "claude-sonnet-4-20250514",
  "demo_mode": false
}
```

---

## Roadmap

See [ROADMAP.md](ROADMAP.md) for what's planned. Honest about what's v1 and what's next.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and PRs welcome.

---

## Agent Plugin

PCIS ships with an [agent plugin](agent-plugin/) that gives any compatible agent persistent, verified memory out of the box.

**Quick setup:**

```bash
cp -r agent-plugin/ ~/.agent/plugins/pcis/
pcis init --dir ~/.pcis
```

The plugin provides three tools to the agent:
- `pcis_add(branch, content, source, confidence)` — add knowledge
- `pcis_search(query, top_k)` — semantic search across the tree
- `pcis_status()` — integrity check + branch/leaf summary

On session start, the plugin automatically verifies Merkle tree integrity and loads current status. See [agent-plugin/README.md](agent-plugin/README.md) for full configuration options.

---

## Agent Integration Skills

Drop-in behavioral guides for AI agents using PCIS. Copy the relevant SKILL.md into your agent's context or skills directory.

| Skill / Adapter | When to use |
|---|---|
| [session-lifecycle](skills/session-lifecycle/SKILL.md) | Session start/end protocol — load context, commit knowledge, update Merkle root |
| [memory-hygiene](skills/memory-hygiene/SKILL.md) | Periodic tree health — run gardener, review pruning candidates, fix echo chambers |
| [knowledge-search](skills/knowledge-search/SKILL.md) | Search before you reason — keyword, semantic, and branch-scoped queries |
| [LangChain adapter](adapters/langchain_memory.py) | Drop-in replacement for `ConversationBufferMemory` - persists facts as verified leaves |

---

## More

- [ROADMAP.md](ROADMAP.md) — where this is going
- [CONTRIBUTING.md](CONTRIBUTING.md) — how to help
- [ARCHITECTURE.md](ARCHITECTURE.md) — deep dive on the architecture

---


## Operational Safety

In March 2026, a misconfigured environment variable caused the gardener to write counter-leaves into a stale copy of the knowledge tree instead of the canonical one. The overly broad cleanup that followed removed 37 legitimate leaves from the stale copy.

The canonical tree was never touched. Merkle integrity caught the divergence. Recovery took minutes.

This incident led to one architectural change: the gardener now refuses to run without an explicit `PCIS_BASE_DIR`. No silent fallback. If it doesn't know which tree it's operating on, it exits with an error. The system fails loud, not wrong.

## Known Limitations

- **Leaf ID format transition** — new leaves use UUID4 (128-bit) IDs for collision safety at scale. Existing trees with legacy 12-char hex IDs load and display correctly; no migration required.

---

## License

**Non-commercial use is 100% free forever. Commercial licensing available now — just email.**

Business Source License 1.1 — free for non-commercial use. Commercial production deployment requires a license.  
Converts to Apache 2.0 on 2030-03-20.  
Commercial inquiries: idwty@proton.me  
See [LICENSE](LICENSE) for full terms.
