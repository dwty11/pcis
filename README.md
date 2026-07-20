# PCIS — Persistent Cognitive Integrity System

Like the amnesiac in *Memento*, an AI agent runs on a memory it can't vouch for — a record that might have been edited yesterday, quietly gone stale, or turned self-contradictory, with nothing checking. And by default it's worse than Memento: the process that writes the record and the process that reads it are the same one. It can amend its own past and then sincerely report the amended version.

Today's AI memory systems ask *"What should I remember?"* PCIS asks: **"Should I still believe it?"**

Tamper-evidence is a commodity — ChainProof, SignLedger, Capsule Protocol, Signatrust, VCP all ship it, and say so: chain verification tells you whether the *log* was touched, not whether the *claim* still holds. An intact record and a stale belief coexist just fine. PCIS is built for the second problem.

On every maintenance pass, an adversarial process — **the gardener** — reads the knowledge tree, with the last five days of session memory as context, and attacks its highest-confidence claims. Challenges that hold become permanent COUNTER entries; nothing is overwritten. Routine counters on operational branches are committed automatically; challenges to constitutional beliefs and new cross-claim links are staged for you to review and apply. And the boundary that keeps the record honest is physical: the signing key lives **off-machine**, so the gardener cannot sign over its own root.

> **RAG retrieves. PCIS proves.**
> **Memory is not the problem. Epistemology is.**

**The full argument:** [Persistent Cognitive Integrity — the case](docs/PCIS.md). This README is the front door; the essay is the *why*.

[![CI](https://github.com/dwty11/pcis/actions/workflows/ci.yml/badge.svg)](https://github.com/dwty11/pcis/actions/workflows/ci.yml) [![License: BSL 1.1](https://img.shields.io/badge/License-BSL_1.1-orange)](https://github.com/dwty11/pcis/blob/main/LICENSE) [![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/) [![Version](https://img.shields.io/badge/version-1.4.1-green)](https://github.com/dwty11/pcis/releases)

Built by [@dwty_11](https://x.com/dwty_11)

---

## Try it in 60 seconds

```bash
git clone https://github.com/dwty11/pcis.git
cd pcis
bash setup.sh
bash start_demo.sh
```

Open `http://localhost:5555` — nine tabs, the full architecture live on synthetic data, zero external calls.

## Break it on purpose

```bash
./verify.sh        # re-derives every leaf hash from content, recomputes the Merkle root
```

Open `data/tree.json`, change one character in any leaf, run `./verify.sh` again — the status flips to `✗ TAMPERED` and names the leaf. Undo the change; `✓ Untampered`. The check re-derives every hash *from content*, so a silently changed byte has nowhere to hide.

## Challenge what your agent believes

```bash
python3 core/knowledge_tree.py --add technical "Postgres beats MySQL for our workload" --confidence 0.7
PCIS_BASE_DIR=. python3 core/gardener.py --dry-run
```

The gardener finds overconfident leaves and generates counter-arguments; `--dry-run` shows the attack without writing anything. It runs on a local Ollama or MLX model — nothing leaves your machine, nothing runs on a schedule unless you set one. It refuses to run without an explicit `PCIS_BASE_DIR` (see **Operational Safety**).

## The Liar's Demo

Two AI agents converse; one later claims it said something different. The math catches the lie — verifiably, offline, in one command. Its `--verify-self` fingerprint is byte-reproducible by anyone.

```bash
cd demo/liars-demo
pip3 install -r requirements.txt
./run_demo.sh --verify-self     # confirm script + fixture fingerprint
./run_demo.sh --text-only       # REFUTED — the substituted claim is caught
```

*(v1 replays six locked canonical runs; the live conversation runner lands in v1.1.)* See [`demo/liars-demo/README.md`](demo/liars-demo/README.md).

---

## What PCIS is *not*

These limits are deliberate — each belongs in a separate layer, and claiming otherwise would be the exact overclaim PCIS exists to catch.

- **Not a blockchain.** Append-only and hash-linked, yes — but no chain, no consensus, no token, no network. One agent, locally verifiable. A blockchain immortalizes data it never questions; PCIS spends its compute attacking its own.
- **Not a vector database.** It challenges what it holds, not just returns it.
- **Not identity binding.** PCIS proves a given keypair committed a given claim at a given time. Binding that keypair to a person or organization is the job of PKI, DIDs, or runtime attestation, on top.
- **Not proof the output came from the tree.** A pristine tree and a hallucination can coexist; PCIS catches the second only insofar as the answer contradicts a leaf the agent claimed to hold.
- **Not equivocation-proof on its own.** A dishonest operator can maintain two trees and show different versions to different parties. Closing that needs an independent witness — a runnable demo witness ships with the Liar's Demo; the production witness is a separate component, not in this repo.
- **Not a state commitment, and no forward secrecy.** The tree is an attestation log — history-shaped, not a current-state snapshot. A compromised key allows backdating; rotation is operator-driven, old records stay verifiable under old keys.

## Operational Safety

In March 2026, a misconfigured environment variable sent the gardener's counter-leaves into a *stale copy* of the tree instead of the canonical one. The canonical tree was never touched, integrity checking caught the divergence, and recovery took minutes. Since then the gardener **fails loud, not wrong**: it refuses to run without an explicit `PCIS_BASE_DIR` — no silent fallback. The incident is why that guard exists.

## Why it matters

When an automated decision faces external audit — SR 11-7, GDPR Art. 22, the EU AI Act — the question is *what the agent knew, when it knew it, and whether that belief survived internal challenge.* PCIS is the layer that answers it: beneath the orchestration layer, beneath the LLM, model-agnostic. Swap GPT for Claude for a local model and the integrity layer doesn't move.

## Go deeper

- [docs/PCIS.md](docs/PCIS.md) — the full argument
- [ARCHITECTURE.md](ARCHITECTURE.md) — how it's built (leads with the adversarial pass)
- [ROADMAP.md](ROADMAP.md) — honest about what's v1 and what's next
- [demo/liars-demo/README.md](demo/liars-demo/README.md) — the offline proof, step by step
- [agent-plugin/](agent-plugin/) and [skills/](skills/) — drop-in agent integration; [LangChain adapter](adapters/langchain_memory.py)
- [CONTRIBUTING.md](CONTRIBUTING.md) — issues and PRs welcome

## Requirements

Python 3.10+, Linux or macOS (Windows not yet — `fcntl`). The gardener and semantic search want a local [Ollama](https://ollama.com) or MLX model (the external validator can also use an LLM API key); without one, both fall back to keyword matching / pre-generated challenges. Demo mode needs nothing.

## License

Business Source License 1.1 — free for non-commercial use, forever. Commercial production deployment requires a license: idwty@proton.me. Converts to Apache 2.0 on 2030-03-20. See [LICENSE](LICENSE).
