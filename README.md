# PCIS — Persistent Cognitive Identity Systems
### The still point of the turning model.

**Give your AI agent a cryptographically verifiable long-term identity — so it never forgets who it is.**

> **License:** Business Source License 1.1 — non-commercial use is free. Commercial deployments require a license (email idwty@proton.me). Converts to Apache 2.0 on 2030-03-20. [See LICENSE](LICENSE)

![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![License](https://img.shields.io/badge/license-BSL%201.1-orange) ![Version](https://img.shields.io/badge/version-1.0.0-green) ![Last Commit](https://img.shields.io/github/last-commit/dwty11/pcis)

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

## What PCIS Does

PCIS is a cognitive infrastructure layer for AI agents. It gives agents persistent, verified memory across sessions — not a database to query, but a knowledge structure the agent genuinely knows, with cryptographic proof of what it knew and when.

The problem: every AI agent deployed today starts each session with no memory of what happened before. At scale — contradictions, hallucinated history, lost client context, no audit trail. PCIS sits beneath the orchestration layer and beneath the LLM, providing the memory and identity continuity that makes agents trustworthy over time.

PCIS is model-agnostic. It runs on GigaChat, GPT-4, Claude, or any local model. Switching the underlying model requires no changes to the memory layer.

For the full architecture: [ARCHITECTURE.md](ARCHITECTURE.md)

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
python demo/adversarial_validator.py --tree data/tree.json --output data/validation_run.json
```

Requires an LLM API key. Set it in `config.json` (copy from `config.example.json`).

---

## Configuration

```json
{
  "base_dir": ".",
  "llm_api_key": "your-key-here",
  "model_name": "your-model-name",
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

## License

Business Source License 1.1 — free for non-commercial use. Commercial production deployment requires a license.  
Converts to Apache 2.0 on 2030-03-20.  
Commercial inquiries: idwty@proton.me  
See [LICENSE](LICENSE) for full terms.

Registered as a Computer Program (Программа для ЭВМ) with Rospatent. Application No. 7009976726, filed 2026-03-11.
