#!/usr/bin/env python3
"""
provenance_ledger.py — append-only JSONL storage for ProvenanceRecords.

WHAT THIS IS
============
One canonical-JSON record per line, appended, at
``$PCIS_BASE_DIR/data/provenance-ledger.jsonl``. Same path convention and
same canonical-JSON form as ``core/events.py``, so a provenance line hashes
and sorts like every other PCIS journal line.

WHAT THIS IS NOT — NO HASH CHAIN
================================
This ledger is append-only, not tamper-evident. It carries no
``prev_event_hash``, no per-record hash, and there is deliberately no
``verify_chain`` here. Do not describe it as tamper-evident, immutable, or
verifiable; a reader can append, edit, or delete a line and nothing in this
module will notice.

The chain is deferred to v0.3 as a design task, because three questions
have to be settled BEFORE building it rather than discovered during:

  1. Field convention. PCIS's journals chain with ``prev_event_hash`` +
     ``event_hash`` over the canonical payload with only ``event_hash``
     excluded (core/events.py:80-83). The shared spec instead describes
     ``prev_hash`` over the prior raw line. Those produce mutually
     unverifiable ledgers, and it is a shared contract, so it needs
     agreement across both implementations first.
  2. Concurrent appends fork the chain. ``events.py`` reads the last hash
     unlocked, before appending (core/events.py:102-108). Two writers can
     read the same predecessor and both chain onto it. Retrieval traces are
     written from HTTP request paths, so this is a live exposure, not a
     theoretical one.
  3. Inclusion proofs now reach the tree root, but a trace cannot use them.
     ``generate_root_proof`` / ``verify_root_proof``
     (core/knowledge_tree.py) emit and check a full leaf-to-tree-root
     envelope, so "provably included under the root this trace recorded"
     is reachable from a proof object — roughly 1.6 KB against a 1.17 MB
     tree, not the whole tree. An earlier version of this note said the
     step was "not reachable without shipping the whole tree", which
     overstated the cost by ~2400x and was read as a reason the design
     stopped there; it is corrected here rather than deleted, because that
     sentence was load-bearing.
     What still blocks the trace specifically is narrower and is a schema
     question, not a proof one: ``content_hash`` below is
     ``sha256(content)`` while a Merkle leaf is
     ``hash_leaf(content, branch, created)``, so per-leaf hashes recorded
     here are in a different namespace from the ones a proof commits to.
     Binding the two means either adopting ``hash_leaf`` or first fixing
     the index-time ``created`` defect that motivated the fork.

Storage location: ``data/``, NOT the spec's ``state/``. ``data/`` is
gitignored (.gitignore:2) and listed in .dockerignore; ``state/`` is
neither, so a ledger of raw claim and answer text there would be committed
to the public remotes and baked into the image.

No external dependencies. Python 3.10+.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from provenance import ProvenanceRecord

DEFAULT_LEDGER_BASENAME = "provenance-ledger.jsonl"


def _base_dir() -> str:
    """Resolved per call, not captured at import.

    An import-time constant would pin the first value ever seen, so a test
    that sets PCIS_BASE_DIR in a fixture would silently write into the
    developer's real repo ``data/``. Mirrors core/events.py:50-54.
    """
    return os.environ.get(
        "PCIS_BASE_DIR",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."),
    )


def _resolve(path: Optional[str]) -> str:
    """Explicit argument wins; otherwise the default under ``data/``."""
    if path is not None:
        return path
    return os.path.join(_base_dir(), "data", DEFAULT_LEDGER_BASENAME)


def ledger_path(path: Optional[str] = None) -> str:
    """Public form of :func:`_resolve`, for callers that want the path."""
    return _resolve(path)


def _read_lines(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [line for line in f if line.strip()]


def append_record(
    record: ProvenanceRecord,
    ledger_path: Optional[str] = None,
    *,
    dedupe: bool = False,
) -> bool:
    """Append one record. Returns True if written, False if skipped.

    ``dedupe=False`` (the default) appends unconditionally — append-only
    means append. ``record_id`` is an idempotency key, but whether a repeat
    write should collapse is the caller's call: the shared spec does not
    rule on it, and this module will not decide it silently. Pass
    ``dedupe=True`` to skip a ``record_id`` already present.

    Note ``dedupe=True`` costs a full read of the ledger and is NOT
    atomic — two concurrent writers can both observe "absent" and both
    append. That is the same class of exposure as the deferred chain work,
    and for the same reason it is not papered over here.
    """
    # NB: the `ledger_path` parameter shadows the module function of the same
    # name inside this body; `_resolve` is the one to use here.
    path = _resolve(ledger_path)

    if dedupe and has_record(record.record_id, path):
        return False

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(record.to_json() + "\n")
    return True


def load_ledger(path: Optional[str] = None) -> list:
    """Return every record, in write order.

    A malformed line RAISES rather than being skipped: a line that will not
    parse is a finding about the ledger, and silently dropping it would hide
    exactly the corruption a reader came looking for. The message names the
    1-indexed line number.
    """
    resolved = _resolve(path)
    out = []
    for i, line in enumerate(_read_lines(resolved), start=1):
        try:
            out.append(ProvenanceRecord.from_json(line))
        except json.JSONDecodeError as e:
            raise ValueError(
                f"{resolved}: line {i} is not valid JSON: {e}"
            ) from e
        except ValueError as e:
            raise ValueError(f"{resolved}: line {i} is not a valid record: {e}") from e
    return out


def has_record(record_id: str, path: Optional[str] = None) -> bool:
    """True if any line already carries this ``record_id``.

    Reads raw JSON rather than constructing records, so a malformed line
    elsewhere in the ledger does not stop a membership check.
    """
    resolved = _resolve(path)
    for line in _read_lines(resolved):
        try:
            if json.loads(line).get("record_id") == record_id:
                return True
        except json.JSONDecodeError:
            continue
    return False


def find_by_record_id(
    record_id: str, path: Optional[str] = None
) -> Optional[ProvenanceRecord]:
    """The first record with this id, or None."""
    resolved = _resolve(path)
    for line in _read_lines(resolved):
        try:
            if json.loads(line).get("record_id") != record_id:
                continue
        except json.JSONDecodeError:
            continue
        return ProvenanceRecord.from_json(line)
    return None


def count_records(path: Optional[str] = None) -> int:
    """Line count, without parsing every record."""
    return len(_read_lines(_resolve(path)))
