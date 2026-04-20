# Changelog

## v1.4.1 (2026-04-20)

**⚠️ Breaking: Merkle root hash algorithm changed.**

Trees signed under v1.4.0 will not verify under v1.4.1 — the root hash of identical content differs between versions. Re-sign any existing trees after upgrading.

Fixes:
- `compute_root_hash` now uses RFC 6962 domain separation (0x00 leaf / 0x01 internal) and MERKLE_PAD for odd levels — fixes CVE-2012-2459 pattern at the root-of-roots level
- `core/signing.py` and `core/multi_agent.py` use try/except import pattern for pip install compatibility
- `docker-entrypoint.sh` passes `--host 0.0.0.0` for container accessibility

## v1.4.0 (2026-04-20)

- Ed25519 root signing (`pcis sign init/root/verify/pubkey`)
- PyNaCl optional dependency under `pcis[signing]`

## v1.3.0 (2026-04-20)

- Enhanced document ingestion (PDF + markdown)
- Decay reporting (`--report`, `--status`)
- Multi-agent support (spec + implementation)
- Agent plugin for compatible AI agent frameworks

## v1.2.0 (2026-04-20)

- `pcis` CLI with 18 subcommands
- Entry point via `[project.scripts]`

## v1.1.0 (2026-04-20)

- Backported: model_agnosticity_monitor, gardener_connections, gardener_healthcheck
- Input sanitization (prompt injection protection)
- Telegram webhook for gardener notifications

## v1.0.0 (2026-04-07)

- Initial release: Merkle tree, adversarial gardener, belief system, semantic search, LangChain adapter, demo server
