# PCIS — Persistent Cognitive Integrity System

Like the amnesiac in *Memento*, an AI agent runs on a memory it can't vouch for — a record that might have been edited yesterday, quietly gone stale, or turned self-contradictory, with nothing checking. And by default it's worse than Memento: the process that writes the record and the process that reads it are the same one. It can amend its own past and then sincerely report the amended version.

Today's AI memory systems ask *"What should I remember?"* PCIS asks: **"Should I still believe it?"**

Tamper-evidence is a commodity — ChainProof, SignLedger, Capsule Protocol, Signatrust, VCP all ship it, and say so: chain verification tells you whether the *log* was touched, not whether the *claim* still holds. An intact record and a stale belief coexist just fine. PCIS is built for the second problem.

On every maintenance pass, an adversarial process — **the gardener** — reads the knowledge tree, with the daily notes of the last five days as context (500 characters of each, 1,500 in all), and attacks its highest-confidence claims. Each challenge it returns is staged for your review when it touches a constitutional belief; otherwise it is committed as a COUNTER leaf, unless a check drops it first. Nothing checks whether a challenge is right, and nothing is overwritten. The connections the gardener suggests between claims are staged too. That gate governs what the gardener writes. It is not yet the whole surface: **direct additions to open branches are not yet gated** — a claim added with `pcis add` lands in the record without staging or certification.

The Merkle root can be signed (Ed25519), and verification pins the signer's public key by fingerprint — a forged signature can't validate under its own embedded key. The gardener holds no key and never signs; signing is a separate, operator-invoked step. The boundary that can keep the record honest even against a compromised host is a physical one — holding that signing key off the machine — but that is a supported deployment pattern, not the default: see [Signing](docs/SIGNING.md).

> **RAG retrieves. PCIS proves.**
> **Memory is not the problem. Epistemology is.**

**The full argument:** [Persistent Cognitive Integrity — the case](docs/PCIS.md). This README is the front door; the essay is the *why*.

[![CI](https://github.com/dwty11/pcis/actions/workflows/ci.yml/badge.svg)](https://github.com/dwty11/pcis/actions/workflows/ci.yml) [![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue)](LICENSE) [![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/) [![Version](https://img.shields.io/badge/version-1.5.0-green)](CHANGELOG.md)

Built by [@dwty_11](https://x.com/dwty_11)

**Status: reference implementation, protocol spec in progress.** This repository holds the record and the checks on it: the knowledge tree and its Merkle verification, the gardener, belief traversal, the retrieval trace, the CLI and the demos. It does not include an agent runtime, which is planned (see [Roadmap](ROADMAP.md#planned-running-an-agent-behind-the-record)), or the off-machine half of signing: `pcis sign root` writes a bare-root signature, but `pcis sign verify` prints `INVALID` unless an approved-root certificate produced off the machine is present, and nothing in this repository produces one. That is by design — see [Signing](docs/SIGNING.md).

---

## Try it in 60 seconds

A legal-assistant agent's knowledge tree holds ~18 ordinary case-file claims — deadlines, statutes, procedure, client facts — and one plant: a well-formatted, entirely fabricated case citation, held at 0.95 confidence with no source, indistinguishable from the real precedents beside it. On a maintenance pass the gardener — **not told which leaf to attack** — reads the tree with recent session memory and challenges its highest-confidence claims. Its strongest counter lands on the fabricated citation, grounded in the record's own verification note: a session log recording that the case returned no results in a case-law reference system.

```bash
git clone https://github.com/dwty11/pcis.git
# or, from Russian networks:
git clone https://gitverse.ru/dwty/pcis.git
cd pcis
./run_demo.sh                 # replay a locked, recorded real gardener run — zero deps, <60s
```

The claim's confidence **moves under challenge** (its net drops from 0.95 into the mid-0.80s; it stays CONFIDENT), the counter is computed against the tree, and the move is surfaced for review. The demo is single-shot and does not write to disk — a live gardener pass writes the counter to the record. PCIS did not prove the ruling doesn't exist; what it makes structural is the verification a court calls a professional duty.

The verification note earns its place — though not the way a single number would suggest. Run the un-hinted gardener repeatedly and it targets the plant at about the same rate with the note or without it (**7/10 vs 6/10**): it is the lone 0.95 model-sourced claim, a structural outlier it attacks either way. What the note changes is the *content* of the challenge. Without the evidence in the record, the gardener can only hedge on doctrine — *"waiver isn't automatic; likely mis-cited."* With it, the same challenge becomes a specific, verified finding: *"resolves to no decision on file; fabricated."* One model (`qwen3.5:9b @ 6488c96`), one tree, one plant; rates vary by snapshot — an illustration, not a benchmark.

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

Open `data/tree.json`, change one character in any leaf's content, run `./verify.sh` again — the status flips to `✗ TAMPERED` and names the leaf. Undo the change; `✓ Untampered`. The check re-derives every hash from content and compares it with the root stored in the same file; what that does not catch is listed under [What PCIS is not](#what-pcis-is-not). This is the commodity half; the gardener challenging its own beliefs — above — is the part that isn't a commodity.

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
- **Not identity binding.** PCIS proves a given keypair committed a given claim. Binding that keypair to a person or organization is the job of PKI, DIDs, or runtime attestation, on top.
- **Not timestamp attestation.** Leaf timestamps are hash-bound, so an edited `created` field is detected — but the *signature* covers no clock: `signed_at` sits beside the root signature rather than inside it, and the bundle check surfaces it without verifying it. Binding time into the signed message is on the roadmap; anchored, third-party-trusted time is a timestamping authority's job, on top.
- **Not proof the output came from the tree.** A pristine tree and a hallucination can coexist; PCIS catches the second only insofar as the answer contradicts a leaf the agent claimed to hold.
- **Not equivocation-proof on its own.** A dishonest operator can maintain two trees and show different versions to different parties. Closing that needs an independent witness — a separate layer, not in this repo.
- **Not a state commitment, and no forward secrecy.** The tree is an attestation log — history-shaped, not a current-state snapshot. A compromised key allows backdating; rotation is operator-driven, old records stay verifiable under old keys.
- **Not a review gate on every gardener write.** A counter committed on an ordinary branch also writes a link to the claim it challenges, without staging, when the model named that claim (a failed link write is ignored); only counters on constitutional beliefs and the connections the gardener suggests wait for review. On the commit path, a challenge is dropped if it names an unknown branch, fails a check, or is judged a near-duplicate.

Seven more are open defects, not design — each is listed on the [Roadmap](ROADMAP.md#open-defects):

- **`verify` trusts its own file.** It compares the re-derived root with the root stored in the same file, so an edit that recomputes every hash and the root passes; only a root held outside the file, such as a signed root, catches it.
- **Confidence, source, id and the pruned flag are not hashed.** A leaf's hash covers its branch, timestamp and content, so changing any of the four passes `verify` and leaves the root unchanged.
- **Links are not checked.** `verify` does not check the links between claims, and the root signature does not cover them.
- The near-duplicate check compares a new counter only with leaves whose content starts with COUNTER:. Counters written in the gardener's current format carry no such prefix, so they are not compared with each other. Traced from the code; not yet reproduced end to end.
- **The already-challenged guard misses new counters.** It looks for a `COUNTER: [id]` prefix that counters in the gardener's current format do not carry.
- **The `data/` guard is partial.** Only `pcis init` and `pcis add` refuse to write into the source repository's own `data/`, and only when no `--dir` or `PCIS_BASE_DIR` is set.
- **Applying a staged synapse writes a text leaf, not a link.** It is written as a `SYNAPSE:` leaf on the `philosophy` branch.

## Operational Safety

In March 2026, a misconfigured environment variable sent the gardener's counter-leaves into a *stale copy* of the tree instead of the canonical one. The canonical tree was never touched, integrity checking caught the divergence, and recovery took minutes. Since then the gardener **fails loud, not wrong**: invoked directly with no `PCIS_BASE_DIR` set, it refuses to run rather than writing into a stale copy. (The `pcis` CLI defaults an unset base directory to the current directory, and `pcis init` and `pcis add` refuse to write into the source repo's own `data/`.) The incident is why that guard exists.

## Why it matters

When an automated decision faces external audit — SR 11-7, GDPR Art. 22, the EU AI Act — the question is *what the agent knew, when it recorded it, and whether that belief survived internal challenge.* (The time is the agent's own clock — see *Not timestamp attestation*, above.) PCIS is built to answer it for the claims an agent commits to its record: beneath the orchestration layer, beneath the LLM, model-agnostic. Swap GPT for Claude for a local model and the integrity layer doesn't move.

## Go deeper

- [docs/PCIS.md](docs/PCIS.md) — the full argument
- [ARCHITECTURE.md](ARCHITECTURE.md) — how it's built
- [ROADMAP.md](ROADMAP.md) — what's in v1 and what's next
- [demo/advocate-demo/README.md](demo/advocate-demo/README.md) — the Advocate Demo, step by step
- [agent-plugin/](agent-plugin/) and [skills/](skills/) — agent integration interfaces (working, not yet used by a third-party agent); [LangChain adapter](adapters/langchain_memory.py)

## Requirements

Python 3.10+, Linux, macOS, or Windows (the replay demo runs anywhere with Python; the gardener's write path uses advisory locking that's Unix-only and degrades to atomic single-writer on Windows). The gardener and semantic search want a local [Ollama](https://ollama.com) or MLX model (the external validator can also use an LLM API key); without one, semantic search falls back to keyword matching, and a live gardener pass needs a model (the replay demo uses a pre-recorded run instead). Demo mode needs nothing.

---

Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
