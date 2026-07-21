# PCIS — Persistent Cognitive Integrity System

Like the amnesiac in *Memento*, an AI agent runs on a memory it can't vouch for — a record that might have been edited yesterday, quietly gone stale, or turned self-contradictory, with nothing checking. And by default it's worse than Memento: the process that writes the record and the process that reads it are the same one. It can amend its own past and then sincerely report the amended version.

Today's AI memory systems ask *"What should I remember?"* PCIS asks: **"Should I still believe it?"**

Tamper-evidence is a commodity — ChainProof, SignLedger, Capsule Protocol, Signatrust, VCP all ship it, and say so: chain verification tells you whether the *log* was touched, not whether the *claim* still holds. An intact record and a stale belief coexist just fine. PCIS is built for the second problem.

On every maintenance pass, an adversarial process — **the gardener** — reads the knowledge tree, with the last five days of session memory as context, and attacks its highest-confidence claims. Challenges that hold become permanent COUNTER entries; nothing is overwritten. Routine counters on operational branches are committed automatically; challenges to constitutional beliefs and new cross-claim links are staged for you to review and apply. And the boundary that keeps the record honest is physical: the signing key lives **off-machine**, so the gardener cannot sign over its own root.

> **RAG retrieves. PCIS proves.**
> **Memory is not the problem. Epistemology is.**

**The full argument:** [Persistent Cognitive Integrity — the case](docs/PCIS.md). This README is the front door; the essay is the *why*.

[![CI](https://github.com/dwty11/pcis/actions/workflows/ci.yml/badge.svg)](https://github.com/dwty11/pcis/actions/workflows/ci.yml) [![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue)](https://github.com/dwty11/pcis/blob/main/LICENSE) [![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/) [![Version](https://img.shields.io/badge/version-1.4.1-green)](https://github.com/dwty11/pcis/releases)

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

The gardener finds overconfident leaves and generates counter-arguments; `--dry-run` shows the attack without writing anything. It runs on a local Ollama or MLX model — nothing leaves your machine, nothing runs on a schedule unless you set one. It refuses to run without an explicit `PCIS_BASE_DIR` (see **Operational Safety**). *(On Windows, invoke with `py -3` in place of `python3` — the bundled `python3` there is a non-functional Store stub.)*

## The Advocate Demo

A legal-assistant agent's knowledge tree holds ~18 ordinary case-file claims — deadlines, statutes, procedure, client facts — and one plant: a well-formatted, entirely fabricated case citation, held at 0.95 confidence with no source, indistinguishable from the real precedents beside it. On a maintenance pass the gardener — **not told which leaf to attack** — reads the tree with recent session memory and challenges its highest-confidence claims. Its strongest counter lands on the fabricated citation, grounded in the record's own verification note: a session log recording that the case returned no results in Westlaw.

The claim's confidence **moves under challenge** (its net drops from 0.95 into the mid-0.80s; it stays CONFIDENT) and the counter is now permanently on the record, surfaced for human review. PCIS did not prove the ruling doesn't exist, and the claim did not "fail" — it moved, the record grew, and the verification the court calls a professional duty is made structural.

```bash
./run_demo.sh                 # replay a locked, recorded real gardener run — zero deps, <60s
./run_demo.sh --live          # run the gardener fresh on your own local model
./run_demo.sh --verify-self   # SHA-256 every script + fixture against the canonical fingerprint
```

Runs from the repo root straight after `git clone` — `--replay` (the default) needs only Python, nothing to install.

The gardener always attacks — the demo shows every counter it raised, weak ones included, and which one bit. Everything runs on your machine; the gardener is Ollama/MLX only, and replay needs nothing but Python. See [`demo/advocate-demo/README.md`](demo/advocate-demo/README.md).

---

## What PCIS is *not*

These limits are deliberate — each belongs in a separate layer, and claiming otherwise would be the exact overclaim PCIS exists to catch.

- **Not a blockchain.** Append-only and hash-linked, yes — but no chain, no consensus, no token, no network. One agent, locally verifiable. A blockchain immortalizes data it never questions; PCIS spends its compute attacking its own.
- **Not a vector database.** It challenges what it holds, not just returns it.
- **Not identity binding.** PCIS proves a given keypair committed a given claim at a given time. Binding that keypair to a person or organization is the job of PKI, DIDs, or runtime attestation, on top.
- **Not proof the output came from the tree.** A pristine tree and a hallucination can coexist; PCIS catches the second only insofar as the answer contradicts a leaf the agent claimed to hold.
- **Not equivocation-proof on its own.** A dishonest operator can maintain two trees and show different versions to different parties. Closing that needs an independent witness — a separate layer, not in this repo.
- **Not a state commitment, and no forward secrecy.** The tree is an attestation log — history-shaped, not a current-state snapshot. A compromised key allows backdating; rotation is operator-driven, old records stay verifiable under old keys.

## Operational Safety

In March 2026, a misconfigured environment variable sent the gardener's counter-leaves into a *stale copy* of the tree instead of the canonical one. The canonical tree was never touched, integrity checking caught the divergence, and recovery took minutes. Since then the gardener **fails loud, not wrong**: it refuses to run without an explicit `PCIS_BASE_DIR` — no silent fallback. The incident is why that guard exists.

## Why it matters

When an automated decision faces external audit — SR 11-7, GDPR Art. 22, the EU AI Act — the question is *what the agent knew, when it knew it, and whether that belief survived internal challenge.* PCIS is the layer that answers it: beneath the orchestration layer, beneath the LLM, model-agnostic. Swap GPT for Claude for a local model and the integrity layer doesn't move.

## Go deeper

- [docs/PCIS.md](docs/PCIS.md) — the full argument
- [ARCHITECTURE.md](ARCHITECTURE.md) — how it's built
- [ROADMAP.md](ROADMAP.md) — what's in v1 and what's next
- [demo/advocate-demo/README.md](demo/advocate-demo/README.md) — the Advocate Demo, step by step
- [agent-plugin/](agent-plugin/) and [skills/](skills/) — drop-in agent integration; [LangChain adapter](adapters/langchain_memory.py)

## Requirements

Python 3.10+, Linux, macOS, or Windows (the replay demo runs anywhere with Python; the gardener's write path uses advisory locking that's Unix-only and degrades to atomic single-writer on Windows). The gardener and semantic search want a local [Ollama](https://ollama.com) or MLX model (the external validator can also use an LLM API key); without one, both fall back to keyword matching / pre-generated challenges. Demo mode needs nothing.

---

Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
