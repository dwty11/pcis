"""root_report.py — Merkle-root fields named for what was observed.

WHY THIS MODULE EXISTS
======================
Two producers (``core/adversarial_validator.py`` and the ``/api/run-validation``
route) each computed a "before" and an "after" Merkle root and wrote both into a
run artifact. Neither writes the tree. So "after" was a PROJECTION — the root the
tree would have if the counters were committed — carrying a name that asserts an
observation nobody made.

The dashboard, given a bare pair of hashes, inferred a transition from
``before !== after`` and rendered "MERKLE ROOT TRANSITION". With a stub model
answering 5/5 that produced, on screen, a root shift for a tree whose bytes on
disk never changed.

A ``tree_written: false`` flag was added to signal this. Nothing read it. A
comment asserted it "tells a consumer this is a projection"; no consumer did.
And the test guarding it asserted the flag's value while the value was a
hardcoded literal, so injecting a real write left the test green.

WHAT THIS MODULE DOES INSTEAD — two subtractions, no new captions
================================================================
1. ``tree_written`` is DERIVED from the file's bytes across the run. A literal
   can claim anything; a value computed from an observation cannot claim a write
   that did not happen.

2. The payload NEVER CARRIES ``merkle_root_after`` unless a write was observed.
   A consumer cannot render a transition from a key that is absent. Where no
   write occurred the projection is emitted as ``merkle_root_projected`` — a
   name that cannot be mistaken for an observation.

And the verdict is computed ONCE, here, rather than inferred by each consumer
from raw fields. ``root_claim`` returns the kind to render, so a client has
nothing left to get wrong. That is the same subtraction that worked on the
display layer: remove the ability to infer, not the temptation.
"""

from __future__ import annotations

import hashlib
import os

# Every verdict root_claim can return. A consumer must handle each; a kind
# outside this set is a bug, not a default. Guarded by test_root_report.
CLAIM_KINDS = ("transition", "unchanged", "projected", "unknown")


def digest_file(path):
    """sha256 of a file's bytes, or None if it is not there.

    None is not an error: a missing tree is a state, and it must not be
    mistaken for "unchanged" (both-None would compare equal) — build_root_report
    handles that explicitly.
    """
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def build_root_report(*, root_before, root_projected, tree_path, digest_before):
    """Root fields for a run artifact, named for what actually happened.

    ``digest_before`` is the value ``digest_file(tree_path)`` returned BEFORE the
    run. This function re-reads the file and derives whether it changed.

    CAPTION PROVENANCE: ``tree_written`` comes from comparing the file's bytes,
    not from the caller's intent. ``merkle_root_after`` is emitted ONLY when that
    comparison says a write occurred, so an artifact cannot state an after-root
    for a tree nobody wrote.
    """
    digest_after = digest_file(tree_path)

    # Both-None means the file was absent throughout — nothing was written.
    # Comparing them directly would call that "unchanged", which is true but
    # arrives for the wrong reason; state it so the next reader sees the case.
    if digest_before is None and digest_after is None:
        tree_written = False
    else:
        tree_written = digest_before != digest_after

    report = {
        "merkle_root_before": root_before,
        "tree_written": tree_written,
    }
    if tree_written:
        report["merkle_root_after"] = root_projected
    else:
        report["merkle_root_projected"] = root_projected
    return report


def root_claim(payload):
    """The verdict a consumer should render, derived once from the artifact.

    Deliberately does NOT trust ``merkle_root_after`` on its own. A legacy
    artifact — or a future producer that forgets — can still carry an after-root
    beside ``tree_written: false``. That pair is exactly the defect this module
    exists to end, so it is read as a projection regardless of what the field is
    called.
    """
    before = payload.get("merkle_root_before")
    after = payload.get("merkle_root_after")
    projected = payload.get("merkle_root_projected")
    written = bool(payload.get("tree_written"))

    if not before:
        return {"kind": "unknown"}

    if written and after:
        kind = "unchanged" if after == before else "transition"
        return {"kind": kind, "before": before, "after": after}

    # Not written. An after-root here is a projection wearing the wrong name.
    value = projected or after
    if value:
        return {"kind": "projected", "before": before, "projected": value}

    return {"kind": "unknown"}
