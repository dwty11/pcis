# Signing and verification

PCIS signs the Merkle root so a verifier can check *who* attested the record, and when.
This page states exactly what is shipped, what is a deployment choice, and how to arrange
the off-machine key separation the design is built around.

## What is shipped

- **Ed25519 signature over the Merkle root.** `pcis sign root` signs the current root hash
  with the private key and records the signature.
- **Pinned-key verification, no embedded-key trust.** `pcis sign verify` checks the signature
  against a **pinned** public-key fingerprint (the SHA-256 of the on-disk `pcis_signing.pub`).
  A signature is never trusted under a key it carries with itself — a forged signature cannot
  validate under its own embedded key. Verification also confirms the signature covers the full
  claim and that the signed root still matches the tree, and it **fails closed** on any mismatch
  (`core/signing.py: verify_claim`).
- **The gardener holds no key and never signs.** The adversarial pass computes the root and can
  hand off a claim, but nothing in `core/gardener.py` signs anything. Signing is a separate,
  operator-invoked step.

## Where the key lives by default

`pcis sign init` writes the keypair into the record's own `data/` directory:

```
data/pcis_signing.key   # private key (0600)
data/pcis_signing.pub   # public key
```

That is **on the same machine as the tree**, and the shipped CLI has **no flag to place it
elsewhere** — `sign init` and `sign root` always use `data/`. So by default the separation the
design describes is *not* in force: an on-host process that can read `data/` can sign the root.
Nothing in the code enforces otherwise.

## Off-machine key separation (a supported deployment pattern)

Holding the private key off the machine — so a compromised host cannot forge the root — is
supported today through the Python API, not through any shipped command. Run from the repo root
with PyNaCl installed:

```python
import os, shutil, sys
sys.path.insert(0, "core")
from signing import generate_keypair, sign_root

# 1. Generate the keypair onto an external volume the host does not retain
#    (a mounted removable disk, a hardware-backed store, a remote-mounted path):
priv_path, pub_path = generate_keypair(key_dir="/Volumes/signer/pcis-keys")

# 2. Verification needs the PUBLIC key in data/. Copy ONLY the .pub back;
#    leave the private key on the external volume.
shutil.copy(pub_path, os.path.join("data", "pcis_signing.pub"))

# 3. Sign the current Merkle root using the off-machine private key:
sign_root(private_key_path="/Volumes/signer/pcis-keys/pcis_signing.key")
```

Now `data/` holds only the public key and the signature; the private key never lands on the
host's own storage. `pcis sign verify` validates against the pinned public key as usual.

**This is discipline, not enforcement.** Nothing in the code checks that the private key is
external — if it is left in `data/`, an on-host process can sign the root. Keeping it off the
machine, and keeping it out of version control, is the operator's responsibility.

## Known limitation

There is no shipped CLI command for the pattern above: `sign init` / `sign root` are hardcoded
to `data/`, so off-machine placement is reachable only through the API shown here. A `--key-dir`
/ `--key-path` flag on those subcommands is the real fix; this page is the honest interim.
