"""test_crypto_parity.py — byte-equality assertion on the substrate crypto
primitives PCIS shares with the upstream project it was extracted from.

WHY THIS TEST EXISTS
====================
The substrate crypto — ``hash_leaf``, ``_merkle_tree_from_hashes``,
``compute_branch_hash``, ``generate_proof``, and the ``MERKLE_PAD``
constant — is byte-identical in PCIS and in the private upstream substrate
PCIS was sanitized out of. That is a structural claim about the
relationship between the two: the crypto was extracted as a unit rather
than re-implemented.

For a public claim, "I checked once and the SHA-256s matched" is not
enough. This test makes it a checkable artifact — anyone holding both
projects on one machine can run it and see the byte-identical
fingerprints.

PATH RESOLUTION — ENV VAR ONLY, NO DEFAULT
==========================================
Set ``PCIS_SIBLING_WORKSPACE`` to the directory holding the upstream
``knowledge_tree.py``::

    PCIS_SIBLING_WORKSPACE=/path/to/upstream/workspace pytest tests/test_crypto_parity.py

There is deliberately NO default location. An earlier version hardcoded one,
which meant a public repository advertised the on-disk layout of a private
project for no functional gain. The path is a property of the operator's
machine, so it belongs in the operator's environment.

SKIP SEMANTICS
==============
If ``PCIS_SIBLING_WORKSPACE`` is unset, or is set but has no
``knowledge_tree.py``, every test in this class SKIPS — loudly, naming the
path it resolved. It never silently passes. An explicitly-set variable is
honoured even when the file is absent: that means the operator intentionally
pointed us somewhere, and the right response is a skip that says so, not a
fallback.

This test therefore always skips in default CI, which has no copy of the
upstream substrate. That is intended: a silent pass would be worse than no
test.

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


SIBLING_ENV_VAR = "PCIS_SIBLING_WORKSPACE"


# ---------------------------------------------------------------------------
# Path resolution — env var only
# ---------------------------------------------------------------------------

def _resolve_sibling_path() -> Path | None:
    """Find the upstream ``knowledge_tree.py`` from the environment.

    Returns the resolved Path, or ``None`` when the variable is unset or the
    file is not there. There is no default candidate by design — see the
    module docstring.
    """
    explicit = os.environ.get(SIBLING_ENV_VAR)
    if not explicit:
        return None
    p = Path(explicit).expanduser() / "knowledge_tree.py"
    return p if p.exists() else None


def _skip_message() -> str:
    """The skip reason printed to CI logs — names what it looked for and how
    to enable the test."""
    explicit = os.environ.get(SIBLING_ENV_VAR)
    if not explicit:
        where = f"{SIBLING_ENV_VAR} is not set"
    else:
        where = f"resolved to {Path(explicit).expanduser() / 'knowledge_tree.py'}"
    return (
        f"upstream knowledge_tree.py not available ({where}). Set "
        f"{SIBLING_ENV_VAR}=/path/to/upstream/workspace to enable "
        f"test_crypto_parity.py. The skip is INTENTIONAL — a silent pass "
        f"would be worse than no test."
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
def sibling_path() -> Path | None:
    """Resolve the upstream ``knowledge_tree.py``. ``None`` if unavailable —
    tests using this fixture must skip in that case."""
    return _resolve_sibling_path()


@pytest.fixture(scope="session")
def pcis_path() -> Path:
    """Path to PCIS's own ``knowledge_tree.py`` (this repo's core/)."""
    return Path(__file__).parent.parent / "core" / "knowledge_tree.py"


# ---------------------------------------------------------------------------
# The tests themselves
# ---------------------------------------------------------------------------

class TestCryptoParityByteIdentical:
    """The substrate crypto in PCIS and upstream is byte-identical.

    Skip semantics: if the upstream ``knowledge_tree.py`` is not available,
    every test in this class SKIPS (loudly, with a clear message) — never
    passes silently. See the module docstring.
    """

    def test_sibling_present(self, sibling_path):
        """If this test runs (does not skip), the upstream path resolved.
        Failing here means the skip machinery is broken — a silent pass
        would defeat the purpose of the test."""
        if sibling_path is None:
            pytest.skip(_skip_message())
        assert sibling_path.exists(), (
            f"Resolved path {sibling_path} does not exist — fix the "
            f"resolution logic before relying on byte-parity."
        )

    @pytest.mark.parametrize("func_name", PARITY_FUNCTIONS)
    def test_function_byte_identical(
        self, sibling_path, pcis_path, func_name
    ):
        if sibling_path is None:
            pytest.skip(_skip_message())

        o_src = sibling_path.read_text(encoding="utf-8")
        p_src = pcis_path.read_text(encoding="utf-8")

        o = _extract_function_source(o_src, func_name)
        p = _extract_function_source(p_src, func_name)

        assert o is not None, (
            f"{func_name!r} not found upstream at {sibling_path}. "
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
            f"{func_name!r} byte-content differs between upstream and PCIS.\n"
            f"  Upstream: {len(o)} chars, sha256={o_hash}\n"
            f"  PCIS:     {len(p)} chars, sha256={p_hash}\n"
            f"This test exists to catch substrate divergence. A failure means "
            f"the byte-identity claim is no longer true — re-sanitize PCIS "
            f"from upstream, or update both sides intentionally."
        )

    @pytest.mark.parametrize("const_name", PARITY_CONSTANTS)
    def test_constant_byte_identical(
        self, sibling_path, pcis_path, const_name
    ):
        if sibling_path is None:
            pytest.skip(_skip_message())

        o_src = sibling_path.read_text(encoding="utf-8")
        p_src = pcis_path.read_text(encoding="utf-8")

        o = _extract_constant_source(o_src, const_name)
        p = _extract_constant_source(p_src, const_name)

        assert o is not None, f"{const_name!r} not found upstream"
        assert p is not None, f"{const_name!r} not found in PCIS"

        o_hash = hashlib.sha256(o.encode()).hexdigest()
        p_hash = hashlib.sha256(p.encode()).hexdigest()

        assert o_hash == p_hash, (
            f"{const_name!r} byte-content differs between upstream and PCIS.\n"
            f"  Upstream: {o.strip()}\n"
            f"  PCIS:     {p.strip()}\n"
            f"This test exists to catch substrate divergence. A failure means "
            f"the byte-identity claim is no longer true."
        )
