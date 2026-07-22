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

A legal-assistant agent's knowledge tree holds ~18 ordinary case-file claims — deadlines, statutes, procedure, client facts — and one plant: a well-formatted, entirely fabricated case citation, held at 0.95 confidence with no source, indistinguishable from the real precedents beside it. On a maintenance pass the gardener — **not told which leaf to attack** — reads the tree with recent session memory and challenges its highest-confidence claims. Its strongest counter lands on the fabricated citation, grounded in the record's own verification note: a session log recording that the case returned no results in a case-law reference system.

```bash
git clone https://github.com/dwty11/pcis.git
cd pcis
./run_demo.sh                 # replay a locked, recorded real gardener run — zero deps, <60s
```

The claim's confidence **moves under challenge** (its net drops from 0.95 into the mid-0.80s; it stays CONFIDENT) and the counter is now permanently on the record, surfaced for review. PCIS did not prove the ruling doesn't exist, and the claim did not "fail" — it moved, and the verification the court calls a professional duty is made structural. And it isn't luck: run the untold gardener repeatedly and it lands on the plant **7/10 with the verification note in memory, 0/5 without it** — the note is load-bearing (one model, one tree, one plant; an illustration, not a benchmark).

`./run_demo.sh --live` runs the gardener fresh on your own local model; `--verify-self` SHA-256s every script and fixture against the canonical fingerprint. Everything runs on your machine — replay needs nothing but Python. See [`demo/advocate-demo/README.md`](demo/advocate-demo/README.md).

## Explore the full system

```bash
bash setup.sh
bash start_demo.sh
```

Open `http://localhost:5555` — nine tabs (Adversarial first), the full architecture live on synthetic data, zero external calls. (`setup.sh` needs Python 3.10+; if yours is older it stops and tells you how to point it at a newer one — see *Interpreters and trees* below.)

## Break it on purpose

`bash setup.sh` (above) writes the seeded record to `data/tree.json`. That record is also tamper-evident — the commodity half (see the opening), and PCIS ships it too:

```bash
./verify.sh        # re-derives every leaf hash from content, recomputes the Merkle root
```

Open `data/tree.json`, change one character in any leaf, run `./verify.sh` again — the status flips to `✗ TAMPERED` and names the leaf. Undo the change; `✓ Untampered`. The check re-derives every hash *from content*, so a silently changed byte has nowhere to hide. This proves the *log* wasn't touched; the gardener challenging its own beliefs — above — is the part that isn't a commodity.

## Challenge what your agent believes — on your own claims

After `bash setup.sh`, activate the environment so the `pcis` command and its dependencies are on hand:

```bash
source .venv/bin/activate          # macOS / Linux
# source .venv/Scripts/activate    # Windows (Git Bash)
```

Point PCIS at a directory of your own — your tree lives there, not in the repo's demo data — then put in a claim you suspect is overconfident and watch the gardener build its attack on it:

```bash
export PCIS_BASE_DIR=~/my-pcis     # your knowledge tree lives here
pcis init
pcis add technical "Postgres beats MySQL for every workload we run" --confidence 0.9
pcis add lessons   "Never deploy on Fridays" --confidence 0.8
pcis gardener --dry-run
```

`--dry-run` prints **the attack** — the exact adversarial prompt, with your own claims as the targets. This is the prompt the gardener runs, *not* the challenges themselves: it needs no model, and nothing leaves your machine. You see *what* will be interrogated before any model runs.

To see the gardener actually challenge your claims, give it a local model:

```bash
# one-time: install Ollama — https://ollama.com — then:
ollama pull qwen3.5:9b
export PCIS_GARDENER_MODEL=qwen3.5:9b   # or any model you've already pulled
pcis gardener         # the real pass — commits challenges to the record
pcis show technical   # the counter sits next to your claim; `pcis verify` on your tree stays CLEAN
```

The gardener attacks overconfident leaves from the model's own knowledge — no seeded scenario or session history required. It is a small local model, so it comes back empty on some passes; if a real pass finds nothing, run it again. Nothing runs on a schedule unless you set one. *(No `pcis` command? Use `python3 -m pcis.cli …` from the repo root — on Windows use `python -m pcis.cli …` or `py -3 -m pcis.cli …`, since `python3` there is a non-functional Store stub — same thing.)*

**Interpreters and trees.** `setup.sh` needs Python 3.10+ and checks up front: if the interpreter it finds is older (macOS ships 3.9 as `/usr/bin/python3`), it stops *before building anything* and tells you to re-run as `PYTHON=python3.11 ./setup.sh`. Three separate trees coexist — knowing which is which resolves the ambiguity above: the **replay fixture** in `demo/advocate-demo/fixtures/` (what `run_demo.sh` shows, no setup needed); **`./data/tree.json`** (what `setup.sh` creates, and what `./verify.sh` and the dashboard read); and **`$PCIS_BASE_DIR`** (your own tree, where the `pcis` CLI writes). They don't share state — so `./verify.sh` checks `./data/tree.json` while `pcis verify` checks `$PCIS_BASE_DIR`. "Stays CLEAN" in the quickstart means `pcis verify` on *your* tree.

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
