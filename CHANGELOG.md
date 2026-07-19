# Changelog

## v1.4.1 (2026-04-20)

A consolidated release bundling the 1.x feature set on top of the initial 1.0 architecture.

**Hash format (breaking change from v1.0):**
- `compute_root_hash` now uses RFC 6962 domain separation (0x00 leaf / 0x01 internal) and MERKLE_PAD for odd levels — closes the CVE-2012-2459 pattern at the root-of-roots level
- Trees signed under v1.0 will not verify under v1.4.1; re-sign existing trees after upgrading

**Features added since v1.0:**
- Ed25519 root signing — operator-controlled key signs the Merkle root; `pcis sign init/root/verify/pubkey` CLI
- Proper binary Merkle tree with inclusion proofs (`generate_proof` / `verify_proof`); `--proof` and `--verify-proof` CLI commands
- Belief decay — exponential decay with configurable half-life (default 180 days), constraints/state branches exempt
- Enhanced document ingestion — PDF and markdown sources
- Multi-agent support (spec + implementation)
- Agent plugin for compatible AI agent frameworks
- `pcis` CLI with 22 subcommands; entry point via `[project.scripts]`
- Input sanitization (prompt-injection protection)
- PyNaCl optional dependency under `pcis[signing]`

**Fixes:**
- `core/signing.py` and `core/multi_agent.py` use try/except import pattern for pip install compatibility
- `docker-entrypoint.sh` passes `--host 0.0.0.0` for container accessibility

## v1.0.0 (2026-04-07)

Initial release: Merkle tree, adversarial gardener, belief system, semantic search, LangChain adapter, demo server.
