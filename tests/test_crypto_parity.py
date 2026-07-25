"""test_crypto_parity.py — byte-equality assertion on the substrate crypto
primitives shared between OpenClaw and PCIS.

WHY THIS TEST EXISTS
====================
The substrate crypto — ``hash_leaf``, ``_merkle_tree_from_hashes``,
``compute_branch_hash``, ``generate_proof``, and the ``MERKLE_PAD``
constant — is byte-identical in OpenClaw and PCIS. This is a structural
claim about the relationship between the two systems: PCIS was sanitized
from OpenClaw's substrate, and the crypto was extracted as a unit
rather than re-implemented.

For a public claim, "I checked once and the SHA-256s matched" is not
enough. This test makes it a checkable artifact — anyone with both
projects on one machine can run it and see the byte-identical
fingerprints.

SKIP SEMANTICS
==============
If OpenClaw's ``knowledge_tree.py`` is not at the configured path,
every test in this class SKIPS — never silently passes. See "Why this
test skips in default CI" in the module docstring above.

PATH RESOLUTION
===============
Resolution order:

    1. ``$WHIS_WORKSPACE`` env var (if set and ``knowledge_tree.py`` exists there)
    2. ``~/.openclaw/workspace/knowledge_tree.py`` (default)

Set ``WHIS_WORKSPACE=/path/to/openclaw/workspace`` to enable this test on
a machine where OpenClaw lives somewhere other than the default location.

PARITY TARGETS
==============
Functions (extracted as exact source text — whitespace, comments, all):

    - ``hash_leaf``
    - ``_merkle_tree_from_hashes``
    - ``compute_branch_hash``
    - ``generate_proof``

Constants:

    - ``MERKLE_PAD`` (top-level assignment)
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Path resolution: CLI > env > default
# ---------------------------------------------------------------------------

def _resolve_whis_workspace_path() -> Path | None:
    """Find OpenClaw's ``knowledge_tree.py``. Resolution order:

    1. ``WHIS_WORKSPACE`` env var (if set — only this path is tried)
    2. ``~/.openclaw/workspace`` default (only if env var unset)

    An explicitly-set ``WHIS_WORKSPACE`` is honored even when the file
    is absent: that means the operator intentionally pointed us
    somewhere, and the right response is skip, not silent fallback.

    Returns the resolved Path or ``None`` if no candidate exists.
    """
    explicit = os.environ.get("WHIS_WORKSPACE")
    if explicit:
        p = Path(explicit).expanduser() / "knowledge_tree.py"
        return p if p.exists() else None
    # Fall through to default only when env var is unset.
    default = Path.home() / ".openclaw" / "workspace" / "knowledge_tree.py"
    return default if default.exists() else None


def _skip_message() -> str:
    """The skip reason printed to CI logs. Names the path it looked for
    and how to enable the test."""
    candidates_seen = []
    if os.environ.get("WHIS_WORKSPACE"):
        candidates_seen.append(f"WHIS_WORKSPACE={os.environ['WHIS_WORKSPACE']}")
    candidates_seen.append(f"default={Path.home() / '.openclaw' / 'workspace'}")
    return (
        "OpenClaw's knowledge_tree.py not found (checked: "
        + ", ".join(candidates_seen)
        + "). Set WHIS_WORKSPACE=/path/to/openclaw/workspace to enable "
        + "test_crypto_parity.py. The skip is INTENTIONAL — a silent pass "
        + "would be worse than no test."
    )


# ---------------------------------------------------------------------------
# Parity targets
# ---------------------------------------------------------------------------

PARITY_FUNCTIONS = [
    "hash_leaf",
    "_merkle_tree_from_hashes",
    "compute_branch_hash",
    "generate_proof",
]
PARITY_CONSTANTS = ["MERKLE_PAD"]


def _extract_function_source(source: str, func_name: str) -> str | None:
    """Return the exact source text of a top-level function (whitespace,
    comments, all included) or ``None`` if not found."""
    import ast
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return "".join(lines[node.lineno - 1:node.end_lineno])
    return None


def _extract_constant_source(source: str, name: str) -> str | None:
    """Return the exact source text of a top-level assignment matching
    ``name`` or ``None`` if not found."""
    import ast
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == name:
                return "".join(lines[node.lineno - 1:node.end_lineno])
    return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def openclaw_path() -> Path | None:
    """Resolve the OpenClaw ``knowledge_tree.py`` path. ``None`` if not
    found — tests using this fixture must skip in that case."""
    return _resolve_whis_workspace_path()


@pytest.fixture(scope="session")
def pcis_path() -> Path:
    """Path to PCIS's own ``knowledge_tree.py`` (this repo's core/)."""
    return Path(__file__).parent.parent / "core" / "knowledge_tree.py"


# ---------------------------------------------------------------------------
# The tests themselves
# ---------------------------------------------------------------------------

class TestCryptoParityByteIdentical:
    """The substrate crypto in PCIS and OpenClaw is byte-identical.

    Skip semantics: if OpenClaw's ``knowledge_tree.py`` is not at the
    configured path, every test in this class SKIPS (loudly, with a
    clear message) — never passes silently. See module docstring.
    """

    def test_openclaw_present(self, openclaw_path):
        """If this test runs (does not skip), the OpenClaw path resolved.
        Failing here means the skip machinery is broken — a silent pass
        would defeat the purpose of the test."""
        if openclaw_path is None:
            pytest.skip(_skip_message())
        assert openclaw_path.exists(), (
            f"Resolved path {openclaw_path} does not exist — fix the "
            f"resolution logic before relying on byte-parity."
        )

    @pytest.mark.parametrize("func_name", PARITY_FUNCTIONS)
    def test_function_byte_identical(
        self, openclaw_path, pcis_path, func_name
    ):
        if openclaw_path is None:
            pytest.skip(_skip_message())

        o_src = openclaw_path.read_text(encoding="utf-8")
        p_src = pcis_path.read_text(encoding="utf-8")

        o = _extract_function_source(o_src, func_name)
        p = _extract_function_source(p_src, func_name)

        assert o is not None, (
            f"{func_name!r} not found in OpenClaw {openclaw_path}. "
            f"Either the function was renamed or this test's PARITY_FUNCTIONS "
            f"list is stale."
        )
        assert p is not None, (
            f"{func_name!r} not found in PCIS {pcis_path}. "
            f"Either the function was renamed or this test's PARITY_FUNCTIONS "
            f"list is stale."
        )

        o_hash = hashlib.sha256(o.encode()).hexdigest()
        p_hash = hashlib.sha256(p.encode()).hexdigest()

        assert o_hash == p_hash, (
            f"{func_name!r} byte-content differs between OpenClaw and PCIS.\n"
            f"  OpenClaw: {len(o)} chars, sha256={o_hash}\n"
            f"  PCIS:     {len(p)} chars, sha256={p_hash}\n"
            f"This test exists to catch substrate divergence. A failure means "
            f"the byte-identity claim is no longer true — re-sanitize PCIS "
            f"from OpenClaw, or update both sides intentionally."
        )

    @pytest.mark.parametrize("const_name", PARITY_CONSTANTS)
    def test_constant_byte_identical(
        self, openclaw_path, pcis_path, const_name
    ):
        if openclaw_path is None:
            pytest.skip(_skip_message())

        o_src = openclaw_path.read_text(encoding="utf-8")
        p_src = pcis_path.read_text(encoding="utf-8")

        o = _extract_constant_source(o_src, const_name)
        p = _extract_constant_source(p_src, const_name)

        assert o is not None, f"{const_name!r} not found in OpenClaw"
        assert p is not None, f"{const_name!r} not found in PCIS"

        o_hash = hashlib.sha256(o.encode()).hexdigest()
        p_hash = hashlib.sha256(p.encode()).hexdigest()

        assert o_hash == p_hash, (
            f"{const_name!r} byte-content differs between OpenClaw and PCIS.\n"
            f"  OpenClaw: {o.strip()}\n"
            f"  PCIS:     {p.strip()}\n"
            f"This test exists to catch substrate divergence. A failure means "
            f"the byte-identity claim is no longer true."
        )
