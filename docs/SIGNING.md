# Signing and verification

PCIS signs the Merkle root so a verifier can check **who** attested the record and **that the
record is intact**. The bare-root signature covers the root hash and nothing else, so the
`signed_at` in `root_signature.json` is contextual metadata recorded beside the signature rather
than attested by it — the bundle check surfaces it, nothing verifies it. The off-machine
approved-root certificate covers a wider claim (root, combined root, tree snapshot, counts,
chain position) but carries no time field at all. Timestamp attestation is a roadmap item;
anchored third-party time belongs to a timestamping authority.
This page states exactly what is shipped, what is a deployment choice, and how to arrange
the off-machine key separation the design is built around.

## What is shipped

- **Ed25519 signature over the Merkle root.** `pcis sign root` signs the current root hash
  with the private key and records the signature.
- **Pinned-key verification, no embedded-key trust.** `pcis sign verify` checks an
  *approved-root certificate* against a **pinned** public-key fingerprint (the SHA-256 of the
  on-disk `pcis_signing.pub`). A signature is never trusted under a key it carries with itself —
  a forged signature cannot validate under its own embedded key. Verification also confirms the
  signature covers the full claim and that the signed root still matches the tree, and it
  **fails closed** on any mismatch (`core/signing.py: verify_claim`). What *produces* that
  certificate — and why a bare `sign root` then `sign verify` prints `INVALID` — is covered next.
- **The gardener holds no key and never signs.** The adversarial pass computes the root, but
  nothing in `core/gardener.py` signs anything — and no command in this repo assembles the
  approved-root claim either (that is the off-machine half, below). Signing is a separate,
  operator-invoked step.

## Verification, and the two signing artifacts

`sign root` and `sign verify` deal with **two different artifacts** — do not conflate them:

- **`data/root_signature.json`** — written by `pcis sign root`. A *bare-root* signature: the
  Ed25519 signature over the current Merkle root hash, plus the public key and a timestamp. It is
  what `pcis audit export --sig` consumes. This is the artifact the on-machine `sign root` step
  produces.
- **`data/approved_root_cert.json`** — the *full-claim* certificate that `pcis sign verify` checks
  (`verify_claim`: pinned fingerprint + signature over the full canonical claim + tree-consistency,
  fail-closed). It is **not** written by `sign root`.

`pcis sign verify` expects `approved_root_cert.json`, and producing that cert is the **off-machine
ratification ceremony** — the whole point of the producer/ratifier split: the claim is approved by a
party outside the machine that runs the substrate. **That ceremony tooling (`pcis_prepare_claim.py`
/ `pcis_verify_claim.py`) is not shipped in this repository.** This repo ships the on-machine half —
key handling, `sign root`, and the *verifier* — not the off-machine producer of the cert.

So running the full chain on a fresh clone:

```bash
pcis sign init     # -> ~/.pcis/keys/pcis_signing.{key,pub}
pcis sign root     # -> data/root_signature.json   (bare-root signature)
pcis sign verify   # -> INVALID — no approved_root_cert.json at data/approved_root_cert.json
```

`sign verify` printing **`INVALID — no approved_root_cert.json`** is **expected, not a breakage**:
no on-machine command writes the full-claim cert, because that is the off-machine ratifier's job and
its tooling lives outside this repo. `sign root` gives you the bare-root signature for audit export;
a *passing* `sign verify` requires the off-machine-produced `approved_root_cert.json`. (The verifier
itself is exercised with hand-built certs in `tests/test_claim_verify_alignment.py` — both through
the Python API (`verify_claim`) and through the CLI `pcis sign verify`.)

## Where the key lives by default

`pcis sign init` writes the keypair **outside the record directory**, into a dedicated key
directory created mode `0700`:

```
~/.pcis/keys/pcis_signing.key   # private key (0600)
~/.pcis/keys/pcis_signing.pub   # public key
```

`PCIS_KEY_DIR` overrides the location. The key directory is deliberately **not** derived from
`--dir` / `PCIS_BASE_DIR`: the CLI sets that to the current directory when unset, so a
base-relative key dir would put the key back inside whatever checkout the command ran from.
Tests set `PCIS_KEY_DIR` to stay off the real home directory — that isolation is the test
harness's doing, not a property of the library. A key left at the legacy in-tree path
`data/pcis_signing.key` is still read, with a warning — the fallback keeps existing installs
verifying, it does not bless the location.

This keeps the key out of the record directory and out of the project tree. It does **not** move
the key off the host: the default keypair is still **on the same machine as the tree**. Use
`--key-dir` / `--key-path` to place the keypair or private key elsewhere (see CLI reference
below). So by default the separation the design describes is *not* in force: an on-host process
running as that user can read the key directory and sign the root. Nothing in the code enforces
otherwise.

## Off-machine key separation (a supported deployment pattern)

Holding the private key off the machine — so a compromised host cannot forge the root — is
supported through the CLI. From the repo root:

```bash
# 1. Generate the keypair onto an external volume the host does not retain
#    (a mounted removable disk, a hardware-backed store, a remote-mounted path):
pcis sign init --key-dir /Volumes/signer/pcis-keys

# 2. Copy ONLY the public key back to the local key dir; leave the private key on the volume:
cp /Volumes/signer/pcis-keys/pcis_signing.pub ~/.pcis/keys/pcis_signing.pub

# 3. Sign the current Merkle root using the off-machine private key:
pcis sign root --key-path /Volumes/signer/pcis-keys/pcis_signing.key
```

Now `data/` holds only the public key and the signature; the private key never lands on the
host's own storage. (`pcis sign verify` still needs the off-machine-produced
`approved_root_cert.json` described above — a bare `sign root` then `sign verify` prints `INVALID`
by design, not because the off-machine key placement failed.)

**This is discipline, not enforcement.** Nothing in the code checks that the private key is
external — if it is left in `data/`, an on-host process can sign the root. Keeping it off the
machine, and keeping it out of version control, is the operator's responsibility.

## CLI reference

| Command | Flag | Effect |
|---------|------|--------|
| `pcis sign init` | `--key-dir PATH` | Write keypair to `PATH/` instead of the default key dir (`$PCIS_KEY_DIR`, else `<BASE>/keys` when `PCIS_BASE_DIR` is set, else `~/.pcis/keys`) |
| `pcis sign root` | `--key-path PATH` | Sign with private key at `PATH` instead of `<KEY_DIR>/pcis_signing.key` |
| `pcis sign verify` | `--key-path PATH` | Verify using public key at `PATH` instead of `<KEY_DIR>/pcis_signing.pub` |

The same pattern is available via the Python API:

```python
from signing import generate_keypair, sign_root

priv_path, pub_path = generate_keypair(key_dir="/Volumes/signer/pcis-keys")
sign_root(private_key_path="/Volumes/signer/pcis-keys/pcis_signing.key")
```
