# PCIS — Persistent Cognitive Identity Systems
### The still point of the turning model.

**PCIS gives an AI agent a persistent, verifiable identity — so it stays itself across sessions, model changes, and restarts.**

> **License:** Business Source License 1.1 — non-commercial use is free. Commercial deployments require a license (email idwty@proton.me). Converts to Apache 2.0 on 2030-03-20. [See LICENSE](LICENSE)

PCIS is a cognitive infrastructure layer for AI agents. It gives agents persistent, verified memory across sessions — not a database to query, but a knowledge structure the agent genuinely knows, with cryptographic proof of what it knew and when.

The problem it solves: every AI agent deployed today starts each session with no memory of what happened before. At scale, this means agents contradict themselves, lose client context, hallucinate history, and produce outputs that cannot be audited. PCIS sits beneath the orchestration layer and beneath the LLM, providing the memory and identity continuity that makes agents trustworthy over time.

PCIS is model-agnostic. It runs on GigaChat, GPT-4, Claude, or any local model. Switching the underlying model requires no changes to the memory layer. The architecture is designed to run entirely on-premises with no external dependencies beyond the LLM of your choice.

For a full description of the six architectural contributions — knowledge tree, Merkle integrity, adversarial pass, gap-scan, pruning, and model-agnostic design — see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Prerequisites

- Python 3.10+
- pip
- A LLM API key (for adversarial validation; optional for demo mode)

---

## Install

```bash
git clone https://github.com/dwty11/pcis.git
cd pcis
bash setup.sh
```

This installs dependencies, creates the `data/` directory, and seeds it with the demo knowledge tree.

---

## Run the Demo

```bash
python demo/server.py
```

Open `http://localhost:5000` in your browser. The demo UI has five tabs:

1. **Boot** — agent startup with Merkle integrity check
2. **Knowledge Tree** — browse the verified knowledge structure
3. **Query** — ask the agent questions; answers are pinned to specific verified leaves
4. **Adversarial** — run an adversarial pass; watch counter-leaves get generated
5. **External LLM Validation** — full validation run with before/after Merkle roots

The demo runs on `demo_tree.json` — a synthetic knowledge tree with realistic structure and zero personal data.

---

## Run Gardener (Nightly Maintenance)

The gardener performs three operations: adversarial pass, gap-scan, and pruning review.

```bash
PCIS_BASE_DIR=/path/to/your/data python core/gardener.py
```

Recommended: run as a nightly cron job. The gardener outputs a summary of staged changes for review.

---

## Run Adversarial Validation

To run a standalone adversarial validation pass against your knowledge tree:

```bash
python demo/adversarial_validator.py --tree data/tree.json --output data/validation_run.json
```

Requires an LLM API key. Set it in `config.json` (copy from `config.example.json`).

---

## Configuration

Copy `config.example.json` to `config.json` and fill in your values:

```json
{
  "base_dir": ".",
  "llm_api_key": "your-key-here",
  "model_name": "your-model-name",
  "demo_mode": false
}
```

---

## License

Business Source License 1.1 — free for non-commercial use. Commercial production deployment requires a license.  
Converts to Apache 2.0 on 2030-03-20.  
Commercial inquiries: idwty@proton.me  
See [LICENSE](LICENSE) for full terms.
