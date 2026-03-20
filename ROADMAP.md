# PCIS Roadmap

Honest about what v1.0 is and what comes next.

---

## v1.0 (current)

- [x] Persistent knowledge tree — JSON-based, branch/leaf structure
- [x] Merkle integrity verification — SHA-256 root hash, tamper-evident
- [x] Adversarial pass — external LLM challenges high-confidence leaves, generates COUNTER entries
- [x] Gap-scan — reads session logs, finds knowledge not yet committed to tree
- [x] Pruning protocol — flags stale and low-confidence leaves for review
- [x] Model-agnostic design — swap LLM without touching memory layer
- [x] Demo UI — five-tab Flask app, runs locally in 60 seconds

---

## v1.1 — Making it actually runnable anywhere

- [ ] Full end-to-end test suite — demo boots and passes all tabs without manual intervention
- [ ] Docker image — `docker run pcis/demo` with no local Python setup
- [ ] Proper Merkle tree — balanced binary tree with branch proofs, not just root hash
- [ ] Semantic search — embedding-based query, not keyword match
- [ ] Config validation — helpful errors when config.json is missing or malformed

---

## v1.2 — First real agent integration

- [ ] LangChain adapter — PCIS as a memory provider for LangChain agents
- [ ] OpenAI function calling integration — agent reads/writes tree via structured API
- [ ] Webhook support — gardener posts summary to Slack/Discord after nightly run
- [ ] Multi-agent shared tree — multiple agents reading from one verified knowledge source

---

## v2.0 — Institutional deployment

- [ ] Role-based access to tree branches (read/write/admin)
- [ ] Distributed Merkle tree — multiple nodes, consensus on root hash
- [ ] Compliance export — generate audit-ready reports from tree history
- [ ] Dashboard — web UI for tree health, adversarial history, pruning log
- [ ] Hosted option — managed PCIS for teams that don't want to self-host

---

## Known limitations in v1.0

- Merkle integrity is root-hash only (not full branch proofs)
- Query is keyword search, not semantic
- Gardener requires local Ollama — no cloud LLM option yet
- No authentication on demo server
- No automated tests

These are real gaps. If any of them block you — open an issue.

---

*The still point of the turning model — just needs the turning mechanism to be fully functional.*
