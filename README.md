# PCIS — Persistent Cognitive Identity Systems
### The still point of the turning model.

**Git for knowledge and beliefs. Give your AI agent a cryptographically verifiable long-term identity — so it never forgets who it is, what it knows, or why.**

> **License:** Business Source License 1.1 — non-commercial use is free. Commercial deployments require a license (email idwty@proton.me). Converts to Apache 2.0 on 2030-03-20. [See LICENSE](LICENSE)

[![CI](https://github.com/dwty11/pcis/actions/workflows/ci.yml/badge.svg)](https://github.com/dwty11/pcis/actions/workflows/ci.yml) [![License: BSL 1.1](https://img.shields.io/badge/License-BSL_1.1-orange)](https://github.com/dwty11/pcis/blob/main/LICENSE) [![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/) [![Version](https://img.shields.io/badge/version-1.0.0-green)](https://github.com/dwty11/pcis/releases) [![Last Commit](https://img.shields.io/github/last-commit/dwty11/pcis)](https://github.com/dwty11/pcis/commits/main)

---

Current agents amnesia on every restart → contradictions, lost context, no audit trail.  
PCIS fixes that with a **persistent Merkle-anchored knowledge tree** + a **self-challenging adversarial gardener**.

---

## Try it in 60 seconds

```bash
git clone https://github.com/dwty11/pcis.git
cd pcis
bash setup.sh
python demo/server.py
```

Open `http://localhost:5555` — five tabs showing the full architecture live.

---

## Quick Start with Docker

```bash
docker compose up
```

Open `http://localhost:5555`

On first run, pull the embedding model for semantic search:

```bash
docker compose exec ollama ollama pull nomic-embed-text
```

---

## See It in Action

**Boot — Merkle integrity check, computed in real time:**
![Boot - Merkle Verified](docs/screenshots/boot-verified.png)

**Knowledge Tree — 5 branches, 19 leaves, Merkle root visible:**
![Knowledge Tree](docs/screenshots/tree.png)

**Query — answers pinned to verified leaves with SHA-256 hashes:**
![Query Result](docs/screenshots/query-result.png)

**Adversarial — self-challenge generating counter-arguments:**
![Adversarial Pass](docs/screenshots/adversarial.png)

---

## What PCIS Does

PCIS is a cognitive infrastructure layer for AI agents. It gives agents persistent, verified memory across sessions — not a database to query, but a knowledge structure the agent genuinely knows, with cryptographic proof of what it knew and when.

The problem: every AI agent deployed today starts each session with no memory of what happened before. At scale — contradictions, hallucinated history, lost client context, no audit trail. PCIS sits beneath the orchestration layer and beneath the LLM, providing the memory and identity continuity that makes agents trustworthy over time.

PCIS is model-agnostic. It runs on GPT-4, Claude, Llama, or any local model — including GigaChat for on-prem deployments. Switching the underlying model requires no changes to the memory layer.

For the full architecture: [ARCHITECTURE.md](ARCHITECTURE.md)

---

## PCIS as External Memory Continual Learning (EMCL)

Continual learning — teaching AI systems to accumulate knowledge over time without forgetting what they already know — is one of the central unsolved problems in AI research. Traditional approaches update model weights directly, which leads to catastrophic forgetting: new knowledge overwrites old.

PCIS takes a different path. Instead of retraining the model, it externalizes memory into a structured, verifiable tree:

- The **knowledge tree** functions as a replay buffer — prior knowledge is never overwritten, only extended or challenged
- The **adversarial gardener** applies stability pressure — high-confidence beliefs are challenged nightly, preventing overfit to recent context
- The **gap-scan** drives plasticity — it identifies what the agent should know but doesn't, targeting learning where it's needed
- The **pruning protocol** manages forgetting deliberately — stale knowledge is flagged and removed by design, not by accident

This architecture maps directly onto the stability-plasticity tradeoff that makes continual learning hard. The difference: PCIS does it at the knowledge layer, without touching model weights, and with cryptographic proof of every state.

---

## Six Contributions

1. **Persistent Knowledge Tree** — structured memory that survives session restarts
2. **Merkle Integrity** — cryptographic proof of what the agent knew and when
3. **Adversarial Pass** — external LLM challenges existing knowledge, generates counter-leaves
4. **Gap-Scan** — finds what the agent *doesn't* know, not just what's wrong
5. **Pruning Protocol** — stale knowledge is flagged and removed; the tree stays sharp
6. **Model-Agnostic** — swap the LLM without touching the memory layer

---

## Demo Tabs

| Tab | What it shows |
|-----|---------------|
| **Boot** | Live Merkle root computation — pass or fail, computed in real time |
| **Knowledge Tree** | Browse the verified knowledge structure, branch by branch |
| **Query** | Ask questions — answers pinned to specific verified leaves |
| **Adversarial** | Counter-leaves generated automatically by challenging high-confidence entries |
| **External LLM Validation** | Full validation run with before/after Merkle roots |

The demo runs on `demo_tree.json` — a clean synthetic knowledge base, zero personal data.

---

## Prerequisites

- Python 3.10+
- pip
- An LLM API key (for adversarial validation; optional for demo mode)

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

The validator supports three providers — set `llm_provider` in `config.json`:

| Provider | `llm_provider` | API key |
|----------|---------------|---------|
| Anthropic | `"anthropic"` | `llm_api_key` in config.json or `ANTHROPIC_API_KEY` env var |
| OpenAI | `"openai"` | `llm_api_key` in config.json or `OPENAI_API_KEY` env var |
| Ollama (local, default) | `"ollama"` | No key required — runs against `http://localhost:11434` |

If no provider is configured, defaults to Ollama. Falls back to pre-generated challenges if no API key is found.

---

## Configuration

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

## More

- [ROADMAP.md](ROADMAP.md) — where this is going
- [CONTRIBUTING.md](CONTRIBUTING.md) — how to help
- [ARCHITECTURE.md](ARCHITECTURE.md) — deep dive on the six contributions

---

## Known Limitations

- **Leaf ID collision risk at scale** — leaf IDs are the first 12 hex characters of the leaf hash (48 bits of entropy). Collision probability becomes non-negligible above ~16 million leaves. Suitable for single-agent and small team deployments; multi-agent shared trees at scale should await the v2.0 ID scheme.

---

## License

**Non-commercial use is 100% free forever. Commercial licensing available now — just email.**

Business Source License 1.1 — free for non-commercial use. Commercial production deployment requires a license.  
Converts to Apache 2.0 on 2030-03-20.  
Commercial inquiries: idwty@proton.me  
See [LICENSE](LICENSE) for full terms.

Registered as a Computer Program (Программа для ЭВМ) with Rospatent. Registration No. 2026617854, registered 2026-03-20.
