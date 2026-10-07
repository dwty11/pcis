# Changelog

## v1.5.0 (2026-10-07)

**Breaking:**

- **`--verify-proof` needs an anchor from outside the proof.** It refuses to run without `--root <hex>` or
  `--cert <approved-root-cert.json>`. Before this, a verifier that took its anchor from the envelope under test
  accepted a fabricated proof over a leaf that was in no tree, including one with an empty path. Inclusion proofs
  also now reach the signed root: `generate_branch_path`, `generate_root_proof` and `verify_root_proof` add the hop
  from a branch root to the tree root.

**Added:**

- **Verified retrieval trace.** `ProvenanceRecord` v0.2: the leaf IDs fed to a model are logged with content hashes
  and re-verified against the tree at read time (`resolves` / `drifted` / `gone` / `withdrawn`), on five retrieval
  paths. A comparison that cannot fail renders no verdict rather than a pass.
- **Provenance ledger.** One canonical-JSON record per line at `data/provenance-ledger.jsonl`; append-only, and
  deliberately not hash-chained.
- **Schema v0.2:** the `attestation` record kind and the `agent` actor.
- **Key flags on `pcis sign`:** `init --key-dir`, `root --key-path` and `verify --key-path`, so keys can live off
  the default location without the Python API.
- **`pcis gardener --dry-run`** prints the exact adversarial prompt, with your own claims as the targets, and needs
  no model.
- **Contributor hooks:** `scripts/install-hooks.sh` prints which patterns its pre-push gate uses and warns when it
  would cover less than before; bypasses found by an adversarial pass are closed, and `scripts/test-hooks.sh` keeps
  seven `BYPASS-` controls for them.

**Changed:**

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
- **Demo replaced.** Removed the Liar's Demo (`demo/liars-demo/`) with its external chat-service dependency; superseded by the **Advocate Demo** (`demo/advocate-demo/`), which demonstrates the wedge — single-agent self-challenge — rather than the tamper-evidence commodity. A legal-assistant agent holds a fabricated case citation at 0.95 confidence; the gardener, untold which leaf to attack, challenges it against the record's own verification note. The claim's confidence moves under challenge and the challenge is surfaced for review — it is not proven false and does not "fail"; the challenge is shown; the replay writes nothing.
- **PyNaCl is a core dependency;** the `signing` extra stays for compatibility.
- **Dependency floors** raised to the first fixed release of each, to clear the security advisories open against them
  on 2026-07-27.
- **The gardener defaults to `qwen3.5:9b`,** the model the demo and its hit-rate figures were measured on.
- **`setup.sh` stops on Python older than 3.10** instead of building an environment that cannot finish.
- **`pcis init` and `pcis add` refuse to write a user's tree into the source repository's own `data/`** when no
  `--dir` or `PCIS_BASE_DIR` is set.

**Fixed:**

- **Fix (gardener):** `core/gardener.py` now passes `think:false` to Ollama. Thinking-capable models (the qwen3 family, including the gardener's default `qwen3.5:9b`) previously routed their answer to a separate `thinking` field and returned an empty `response`, so the gardener parsed **0** counter-arguments — it had not worked on its own default model. Ignored by non-thinking models.
- The gardener no longer drops output that a model wraps in a numbered or bulleted list.
- The external validator no longer writes a canned challenge when a call fails: an unsupported provider raises, and
  a failed call writes no leaf and is recorded with its error.
- A run artifact no longer names a Merkle root the tree never had: a root that was not written ships as
  `merkle_root_projected`.
- The dashboard's integrity tab now detects the tampering it says it detects.
- The demo reports an empty gardener pass as empty, instead of showing a challenge that did not happen.
- `pcis search` without Ollama prints a remedy that works; four retrieval entry points that raised on invocation are
  repaired.
- Windows and cp1251 (Russian-locale Windows): the replay demo runs from a cold clone with no manual steps, and
  `verify.sh` no longer reports TAMPERED on an unmodified tree.

**Docs:**

- **Docs honesty pass.** Corrections to claims about the gardener's model paths, retrieval-trace
  coverage, attestation bounds, and ceremony tooling. The load-bearing one: a signature over the
  Merkle root proves *who* attested the record and *that it is intact* — it does **not** attest
  *when*. `signed_at` is contextual metadata recorded beside the signature; binding time into the
  signed message is now a named roadmap item.
- **A second honesty pass.** Claims in the README, ARCHITECTURE, ROADMAP, SIGNING, the memory-hygiene skill and the
  Advocate demo's README are brought back to what the code does; seven open defects are named in the ROADMAP and in
  the README's limits; a status paragraph opens the README; and the ROADMAP gains a section for planned runtime work.
- **The essay, `docs/PCIS.md`:** a gardener challenge is described as a recorded objection that nothing checks is
  right, and the paragraph now says which counters are committed automatically and which are staged for review.

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
