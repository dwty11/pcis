# Contributing to PCIS

PCIS is a v1.x project — the architecture is solid, the implementation has known gaps. Both are worth working on.

---

## Ways to contribute

**Bug reports** — if the demo doesn't run as described in README, open an issue with your OS, Python version, and the exact error.

**Feature requests** — check [ROADMAP.md](ROADMAP.md) first. If it's on the roadmap, +1 it in issues. If it's not, open a discussion.

**Pull requests** — welcome. Focus areas where PRs have the most impact:
- Test coverage — current suite covers core tree, synapses, belief traversal, search API, and ingestion; integration tests and edge cases welcome
- Docker setup
- LangChain / agent framework adapters

**Using PCIS in a real project** — tell us. Open an issue titled "Using PCIS for [X]" and describe your use case. This is the most valuable signal we can get right now.

---

## Ground rules

- Keep PRs focused — one thing at a time
- If you're changing core architecture (tree structure, Merkle hashing, gardener logic), open an issue first
- No breaking changes to the JSON tree format without a migration path

---

## License note

PCIS is licensed under Apache 2.0. Contributions are welcome — by submitting a contribution you agree to license it under the same terms (see [LICENSE](LICENSE)).

---

*Love to hear how you're using PCIS — issues, PRs, and questions all welcome.*
