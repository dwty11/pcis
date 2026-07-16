#!/usr/bin/env python3
"""
signing.py — Ed25519 root signing for PCIS Merkle trees.

Provides cryptographic proof that a specific Merkle root was endorsed
by the holder of a private key at a specific time.

Requires PyNaCl (optional dependency):
    pip install pcis[signing]
"""

import hashlib
import json
import os
import stat
from datetime import datetime, timezone

# --- Optional dependency gate -------------------------------------------

_NACL_AVAILABLE = True
_NACL_IMPORT_ERROR = None

try:
    import nacl.signing
    import nacl.encoding
    import nacl.exceptions
except ImportError as exc:
    _NACL_AVAILABLE = False
    _NACL_IMPORT_ERROR = exc


def _require_nacl():
    """Raise a clear error if PyNaCl is not installed."""
    if not _NACL_AVAILABLE:
        raise RuntimeError(
            "ed25519 signing requires PyNaCl. "
            "Install with: pip install pcis[signing]"
        )


# --- Helpers ------------------------------------------------------------

def _base_dir():
    return os.environ.get(
        "PCIS_BASE_DIR",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."),
    )


def _default_key_path(filename):
    return os.path.join(_base_dir(), "data", filename)


PRIVATE_KEY_FILE = "pcis_signing.key"
PUBLIC_KEY_FILE = "pcis_signing.pub"
SIGNATURE_FILE = "root_signature.json"          # legacy bare-root cert (unused by the verify path)
APPROVED_CERT_FILE = "approved_root_cert.json"  # full-claim approved-root cert (the signing output)


# --- Public API ---------------------------------------------------------

def generate_keypair(key_dir=None):
    """Generate an ed25519 keypair and save to disk.

    Returns (private_key_path, public_key_path).
    Raises FileExistsError if either key file already exists.
    """
    _require_nacl()

    if key_dir is None:
        key_dir = os.path.join(_base_dir(), "data")
    os.makedirs(key_dir, exist_ok=True)

    priv_path = os.path.join(key_dir, PRIVATE_KEY_FILE)
    pub_path = os.path.join(key_dir, PUBLIC_KEY_FILE)

    if os.path.exists(priv_path):
        raise FileExistsError(
            f"Private key already exists: {priv_path}  "
            "Remove it manually before generating a new keypair."
        )
    if os.path.exists(pub_path):
        raise FileExistsError(
            f"Public key already exists: {pub_path}  "
            "Remove it manually before generating a new keypair."
        )

    signing_key = nacl.signing.SigningKey.generate()

    # Write private key (hex-encoded seed)
    with open(priv_path, "w") as f:
        f.write(signing_key.encode(encoder=nacl.encoding.HexEncoder).decode())
    os.chmod(priv_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600

    # Write public key (hex-encoded)
    verify_key = signing_key.verify_key
    with open(pub_path, "w") as f:
        f.write(verify_key.encode(encoder=nacl.encoding.HexEncoder).decode())

    return priv_path, pub_path


def _tree_file():
    """Tree file the gate snapshots. Override with PCIS_TREE_FILE (absolute, or relative to
    the base dir); neutral default: <base>/data/tree.json."""
    override = os.environ.get("PCIS_TREE_FILE")
    if override:
        return override if os.path.isabs(override) else os.path.join(_base_dir(), override)
    return os.path.join(_base_dir(), "data", "tree.json")


def sign_root(tree=None, private_key_path=None):
    """Sign the current Merkle root hash with an ed25519 private key.

    Returns a signature dict and writes it to root_signature.json.
    """
    _require_nacl()

    try:
        from core.knowledge_tree import load_tree, compute_root_hash
    except ImportError:
        from knowledge_tree import load_tree, compute_root_hash

    if tree is None:
        tree = load_tree(_tree_file())
    root_hash = compute_root_hash(tree)

    if private_key_path is None:
        private_key_path = _default_key_path(PRIVATE_KEY_FILE)

    if not os.path.exists(private_key_path):
        raise FileNotFoundError(
            f"Private key not found: {private_key_path}  "
            "Run 'pcis sign init' first."
        )

    with open(private_key_path, "r") as f:
        key_hex = f.read().strip()
    signing_key = nacl.signing.SigningKey(key_hex, encoder=nacl.encoding.HexEncoder)

    signed = signing_key.sign(root_hash.encode())
    signature_hex = signed.signature.hex()

    verify_key = signing_key.verify_key
    public_key_hex = verify_key.encode(encoder=nacl.encoding.HexEncoder).decode()

    result = {
        "root_hash": root_hash,
        "signature": signature_hex,
        "signed_at": datetime.now(timezone.utc).isoformat(),
        "public_key": public_key_hex,
    }

    sig_path = _default_key_path(SIGNATURE_FILE)
    os.makedirs(os.path.dirname(sig_path), exist_ok=True)
    with open(sig_path, "w") as f:
        json.dump(result, f, indent=2)

    return result


def verify_root(tree=None, public_key_path=None, signature_path=None):
    """Verify the ed25519 signature against the current Merkle root.

    Returns a dict with 'valid', 'root_hash', 'signed_at', 'detail'.
    """
    _require_nacl()

    try:
        from core.knowledge_tree import load_tree, compute_root_hash
    except ImportError:
        from knowledge_tree import load_tree, compute_root_hash

    if tree is None:
        tree = load_tree(_tree_file())
    root_hash = compute_root_hash(tree)

    if signature_path is None:
        signature_path = _default_key_path(SIGNATURE_FILE)
    if public_key_path is None:
        public_key_path = _default_key_path(PUBLIC_KEY_FILE)

    if not os.path.exists(signature_path):
        return {
            "valid": False,
            "root_hash": root_hash,
            "signed_at": "",
            "detail": f"Signature file not found: {signature_path}",
        }

    with open(signature_path, "r") as f:
        sig_data = json.load(f)

    # Load public key from the on-disk .pub ONLY. NO fallback to the signature's own
    # embedded public_key — a self-embedded key lets a forged sig validate under its own
    # key (adversarial finding #1). Absent .pub is a hard fail, not an embedded-key path.
    if not os.path.exists(public_key_path):
        return {
            "valid": False,
            "root_hash": root_hash,
            "signed_at": sig_data.get("signed_at", ""),
            "detail": f"Public key file absent: {public_key_path} — refusing embedded-key fallback.",
        }
    with open(public_key_path, "r") as f:
        public_key_hex = f.read().strip()

    if not public_key_hex:
        return {
            "valid": False,
            "root_hash": root_hash,
            "signed_at": sig_data.get("signed_at", ""),
            "detail": "No public key available for verification.",
        }

    result = verify_root_standalone(
        root_hash, sig_data["signature"], public_key_hex
    )
    result["signed_at"] = sig_data.get("signed_at", "")
    return result


def _canonical_claim(obj):
    """Canonical JSON bytes for a claim — the exact form that is signed and that every verify
    path recomputes. Must be byte-stable across all callers or the recomputed forms diverge."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def verify_claim(cert, pin_fpr, snapshot_path=None):
    """Canonical full-claim verification — THE single source of truth shared by the CLI
    `pcis sign verify` and any external caller, so multiple verify paths cannot drift (that drift
    is exactly the bug this closes).

        cert          parsed cert dict: {claim, claim_hash, signature, public_key}
        pin_fpr       the 64-hex PINNED fingerprint; the caller resolves it (sha256 of the
                      on-disk .pub, or the pinned literal). NO embedded-key trust —
                      cert['public_key'] must fingerprint to this pin.
        snapshot_path tree bytes (data/tree.json, or a pulled snapshot for external verification).
                      When given, the SIGNED tree_snapshot_sha256 AND root_hash are re-verified
                      against the actual tree — all four steps, both sides (defense in depth).

    Returns (ok: bool, detail: str). Fail-closed on ANY mismatch.
    """
    _require_nacl()
    try:
        claim = cert["claim"]
        pub = cert["public_key"]
    except (KeyError, TypeError):
        return False, "malformed cert (missing 'claim'/'public_key')"

    # (1) the signing key MUST be the pinned key — no embedded-key trust
    got_fpr = hashlib.sha256(pub.encode()).hexdigest()
    if got_fpr != pin_fpr:
        return False, f"pubkey fingerprint {got_fpr[:16]}… != pinned {str(pin_fpr)[:16]}…"

    # (2) signature covers the FULL canonical claim — tamper ANY field and this fails
    try:
        nacl.signing.VerifyKey(pub, encoder=nacl.encoding.HexEncoder).verify(
            _canonical_claim(claim), bytes.fromhex(cert["signature"]))
    except nacl.exceptions.BadSignatureError:
        return False, "signature INVALID (claim tampered or wrong key)"
    except Exception as exc:  # noqa: BLE001
        return False, f"signature verification error: {exc}"

    # (3) claim_hash identifier is consistent with the signed claim
    if cert.get("claim_hash") != hashlib.sha256(_canonical_claim(claim)).hexdigest():
        return False, "claim_hash mismatch"

    # (4) tree-consistency: the SIGNED snapshot sha + root_hash must match actual tree bytes
    if snapshot_path and os.path.exists(snapshot_path):
        with open(snapshot_path, "rb") as f:
            snap = f.read()
        if hashlib.sha256(snap).hexdigest() != claim.get("tree_snapshot_sha256"):
            return False, "tree_snapshot_sha256 != actual snapshot bytes"
        try:
            from core.knowledge_tree import compute_root_hash, load_tree
        except ImportError:
            try:
                from knowledge_tree import compute_root_hash, load_tree
            except ImportError as exc:
                return False, f"cannot recompute root (knowledge_tree unavailable): {exc}"
        if compute_root_hash(load_tree(snapshot_path)) != claim.get("root_hash"):
            return False, "signed root_hash != Merkle root recomputed over the snapshot"
        return True, "signature by the PINNED key over the full claim + tree-consistent"

    return True, "signature by the PINNED key over the full claim (claim-only; no snapshot given)"


def verify_root_standalone(root_hash_hex, signature_hex, public_key_hex):
    """Pure ed25519 verification without loading any files.

    Parameters:
        root_hash_hex: The Merkle root hash (hex string).
        signature_hex: The ed25519 signature (hex string).
        public_key_hex: The ed25519 public key (hex string).

    Returns dict with 'valid', 'root_hash', 'detail'.
    """
    _require_nacl()

    try:
        verify_key = nacl.signing.VerifyKey(
            public_key_hex, encoder=nacl.encoding.HexEncoder
        )
        verify_key.verify(
            root_hash_hex.encode(),
            bytes.fromhex(signature_hex),
        )
        return {
            "valid": True,
            "root_hash": root_hash_hex,
            "detail": "Signature is valid.",
        }
    except nacl.exceptions.BadSignatureError:
        return {
            "valid": False,
            "root_hash": root_hash_hex,
            "detail": "Signature verification FAILED — root hash or key mismatch.",
        }
    except Exception as exc:
        return {
            "valid": False,
            "root_hash": root_hash_hex,
            "detail": f"Verification error: {exc}",
        }


def export_public_key(public_key_path=None):
    """Return the public key as a hex string.

    Reads from the public key file on disk.
    """
    if public_key_path is None:
        public_key_path = _default_key_path(PUBLIC_KEY_FILE)

    if not os.path.exists(public_key_path):
        raise FileNotFoundError(
            f"Public key not found: {public_key_path}  "
            "Run 'pcis sign init' first."
        )

    with open(public_key_path, "r") as f:
        return f.read().strip()
