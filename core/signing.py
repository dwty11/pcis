#!/usr/bin/env python3
"""
signing.py — Ed25519 root signing for PCIS Merkle trees.

Provides cryptographic proof that a specific Merkle root was endorsed
by the holder of a private key at a specific time.

Requires PyNaCl (optional dependency):
    pip install pcis[signing]
"""

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
SIGNATURE_FILE = "root_signature.json"


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
    """Return the current tree file path (respects PCIS_BASE_DIR at call time)."""
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

    # Load public key — prefer file, fall back to embedded in signature
    if os.path.exists(public_key_path):
        with open(public_key_path, "r") as f:
            public_key_hex = f.read().strip()
    else:
        public_key_hex = sig_data.get("public_key", "")

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
