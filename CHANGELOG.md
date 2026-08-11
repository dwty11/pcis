# Changelog

## Unreleased

- **Signing keys move out of the record directory.** `pcis sign init` now writes the keypair to
  `$PCIS_KEY_DIR`, else `~/.pcis/keys` (created `0700`, private key `0600`), instead of into the
  record's own `data/`. The key directory is deliberately **not** derived from `--dir` /
  `PCIS_BASE_DIR`, because the CLI sets that to the current directory — a base-relative key dir
  would put the key back inside whatever checkout the command ran from.

  `pcis audit export` resolves its public-key anchor through the same path, so the audit anchor
  and the signing path cannot disagree about which key is authoritative.

  **Deprecation window:** key material left at the legacy in-tree `data/` location is still read
  for **one release**, and every such read emits a `RuntimeWarning` naming the path. Move your
  keys to the key directory before the next release, or pass `--key-dir` / `--key-path` /
  `--key` explicitly.
- **Docs honesty pass.** Corrections to claims about the gardener's model paths, retrieval-trace
  coverage, attestation bounds, and ceremony tooling. The load-bearing one: a signature over the
  Merkle root proves *who* attested the record and *that it is intact* — it does **not** attest
  *when*. `signed_at` is contextual metadata recorded beside the signature; binding time into the
  signed message is now a named roadmap item.
- **Demo replaced.** Removed the Liar's Demo (`demo/liars-demo/`) with its external chat-service dependency; superseded by the **Advocate Demo** (`demo/advocate-demo/`), which demonstrates the wedge — single-agent self-challenge — rather than the tamper-evidence commodity. A legal-assistant agent holds a fabricated case citation at 0.95 confidence; the gardener, untold which leaf to attack, challenges it against the record's own verification note. The claim's confidence moves under challenge and the challenge is surfaced for review — it is not proven false and does not "fail"; the record grows.
- **Fix (gardener):** `core/gardener.py` now passes `think:false` to Ollama. Thinking-capable models (the qwen3 family, including the gardener's default `qwen3.5:9b`) previously routed their answer to a separate `thinking` field and returned an empty `response`, so the gardener parsed **0** counter-arguments — it had not worked on its own default model. Ignored by non-thinking models.

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
