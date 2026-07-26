"""test_invariant_comments.py — a comment asserting a property must point at a test.

Roc's meta-finding (2026-07-26): the CAPTION PROVENANCE annotations do real
work, but *nothing fails when a comment and its code diverge*. That produced a
comment claiming an unrecognised status "falls through to UNVERIFIABLE, which
is the safe direction" six lines above ``else: status = "CLEAN"``.

A wrong caption misleads a reader. A comment asserting a **safety property the
code does not have** is worse: the next person reads it as a guarantee and
builds on it. So a claim of that kind has to be executable.

THE CONVENTION
==============
Write it as::

    # INVARIANT(test_unknown_file_status_is_unverifiable): an unrecognised
    # per-file status must never produce CLEAN.

This test resolves every ``INVARIANT(name)`` marker in the scanned sources to a
``def name(`` in tests/, so a claim pointing at nothing fails the suite.

WHAT THIS DOES NOT PROVE
========================
That the named test actually tests the claim. Nothing mechanical can check
that — a human still has to write an honest test. What it removes is the
*silent* case: an invariant comment whose test was renamed, deleted, or never
written at all. Stating the limit rather than implying full coverage is the
same discipline the rest of this module is about.
"""

from __future__ import annotations

import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

# Sources that carry load-bearing invariant claims.
SCANNED = [
    os.path.join("demo", "server.py"),
    os.path.join("core", "retrieval_trace.py"),
    os.path.join("core", "adversarial_validator.py"),
]

MARKER = re.compile(r"INVARIANT\(([A-Za-z_][A-Za-z0-9_]*)\)")


def _all_test_defs():
    defs = set()
    for fname in os.listdir(_HERE):
        if not fname.startswith("test_") or not fname.endswith(".py"):
            continue
        text = open(os.path.join(_HERE, fname), encoding="utf-8").read()
        defs.update(re.findall(r"def (test_[A-Za-z0-9_]+)\s*\(", text))
    return defs


def _markers():
    found = []
    for rel in SCANNED:
        path = os.path.join(_ROOT, rel)
        if not os.path.exists(path):
            continue
        text = open(path, encoding="utf-8").read()
        for name in MARKER.findall(text):
            found.append((rel, name))
    return found


def test_every_invariant_comment_resolves_to_a_real_test():
    defs = _all_test_defs()
    orphans = [(rel, name) for rel, name in _markers() if name not in defs]

    assert not orphans, (
        "invariant comment(s) naming a test that does not exist: "
        + ", ".join(f"{rel} -> {name}()" for rel, name in orphans)
        + ". A comment asserting a property the suite does not check is the "
        "defect this convention exists to prevent."
    )


def test_the_mechanism_is_actually_in_use():
    """A convention nothing uses proves nothing. Guards against the markers
    being quietly stripped, which would make the test above pass vacuously."""
    markers = _markers()

    assert markers, (
        "no INVARIANT(...) markers found in any scanned source — either the "
        "convention was abandoned or SCANNED has gone stale"
    )
