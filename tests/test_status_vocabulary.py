"""test_status_vocabulary.py — a consumer must not hold its own copy of a
producer's status vocabulary.

THE INSTANCE THIS COMES FROM
===========================
`tests/test_boot_manifest.py` hardcoded the server's list of boot statuses. When
`server.py` grew a third state (`UNVERIFIABLE`), the test kept asserting against
its own two-item copy and stayed green — the suite could not see a status it had
never been told about. The fix was to move `BOOT_STATUSES` into `server.py` and
have the test import it; it then caught a missing CSS class within a minute.

That is one shape of a wider defect: **a claim about a value, written far enough
from the value that the two can drift silently.** A duplicated vocabulary is the
version of it that no caption sweep can find, because the duplicate contains no
caption at all — just string literals that happen to agree today.

WHY THE RULE IS "TWO OR MORE MEMBERS"
====================================
Flagging any single vocabulary member is unusable: `pass`, `fail`, `missing` and
`OK` are ordinary English, and the naive rule flags **312 occurrences** across
this repo — a lint nobody runs, which is worse than no lint because it looks
like coverage.

Quoting *two or more distinct members* of one vocabulary is different in kind.
That is not incidental word use; it is modelling the vocabulary, and a file
modelling a vocabulary should import it. That rule flags 11 files, which is a
list a person can actually work through.

HOW THE BASELINE WORKS
======================
`KNOWN` records the duplications that existed when this check was written, each
with a reason. Two tests guard it from both directions:

  - a violation not in KNOWN fails         → the count cannot grow
  - a KNOWN entry that is no longer a
    violation also fails                   → a fixed file must be removed from
                                             KNOWN, so the baseline cannot rot
                                             into a list of things that were
                                             true once

The second is the one that makes it a ratchet rather than a permanent excuse.
"""

from __future__ import annotations

import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

# constant name -> (module that owns it, its members)
VOCABULARIES = {
    "BOOT_STATUSES": (
        os.path.join("demo", "server.py"),
        ["CLEAN", "MODIFIED", "UNVERIFIABLE", "ERROR"],
    ),
    "FILE_STATUSES": (
        os.path.join("demo", "server.py"),
        ["OK", "MODIFIED", "MISSING", "UNTRACKED", "NO_MANIFEST"],
    ),
    "VERIFIER_STATUSES": (
        os.path.join("core", "provenance.py"),
        ["pass", "fail", "skipped"],
    ),
    "RE_VERIFICATION_STATUSES": (
        os.path.join("core", "provenance.py"),
        ["pass", "mismatch", "missing", "retracted"],
    ),
    "ATTEMPT_OUTCOMES": (
        os.path.join("core", "adversarial_validator.py"),
        ["live", "failed"],
    ),
}

# Duplications present when this check was written. Each needs a reason: an
# unexplained exemption is the same problem wearing a different hat.
KNOWN = {
    ("tests/test_e2e.py", "BOOT_STATUSES"):
        "end-to-end assertions on rendered output rather than on the constant",
    ("core/gardener_healthcheck.py", "FILE_STATUSES"):
        "emits its own OK/MISSING health vocabulary that overlaps by accident; "
        "needs a decision on whether it is the same vocabulary at all",
    ("core/verify_memory.py", "FILE_STATUSES"):
        "same overlap question as gardener_healthcheck",
    ("pcis/cli.py", "FILE_STATUSES"):
        "CLI prints status text; overlap may be coincidental",
    ("tests/test_gardener_healthcheck.py", "FILE_STATUSES"):
        "mirrors gardener_healthcheck's own vocabulary",
    ("core/retrieval_trace.py", "VERIFIER_STATUSES"):
        "genuine consumer of provenance.py's vocabulary — real candidate to fix",
    ("core/retrieval_trace.py", "RE_VERIFICATION_STATUSES"):
        "holds all four members verbatim — the clearest real instance",
    ("tests/test_provenance_ledger.py", "VERIFIER_STATUSES"):
        "test-side duplicate of the producer's vocabulary",
    ("tests/test_provenance_ledger.py", "RE_VERIFICATION_STATUSES"):
        "test-side duplicate of the producer's vocabulary",
    ("tests/test_retrieval_trace.py", "VERIFIER_STATUSES"):
        "test-side duplicate of the producer's vocabulary",
    ("tests/test_retrieval_trace.py", "RE_VERIFICATION_STATUSES"):
        "test-side duplicate, all four members",
    ("tests/test_provenance_api.py", "RE_VERIFICATION_STATUSES"):
        "test-side duplicate, all four members",
    ("tests/test_schema_parity.py", "VERIFIER_STATUSES"):
        "holds the constant NAME as a string in its parity list while also "
        "quoting the members — surfaced only once the check stopped accepting "
        "a bare mention as a reference",
    ("tests/test_schema_parity.py", "RE_VERIFICATION_STATUSES"):
        "same shape as the VERIFIER_STATUSES entry above",
}

_SKIP_DIRS = {"__pycache__", ".venv", "node_modules", ".git"}


def _py_files():
    out = []
    for base in ("core", "demo", "pcis", "adapters", "scripts", "tests",
                 "agent-plugin"):
        root = os.path.join(_ROOT, base)
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fn in filenames:
                if fn.endswith(".py"):
                    out.append(os.path.relpath(os.path.join(dirpath, fn), _ROOT))
    return sorted(out)


def _code_names(text):
    """Identifiers appearing as CODE, not in comments or docstrings.

    The first version of this asked `if const in text`, which exempted any file
    that merely *mentioned* the constant — a comment reading
    `# duplicates VERIFIER_STATUSES` was enough to silence the check on that
    file. Substring presence was standing in for "references the constant",
    which is the same substitution this module exists to catch, committed
    inside the check itself. Caught by its own red-first plant, whose comment
    named the constant and thereby exempted the plant.

    tokenize gives NAME tokens only for real identifiers, so a mention in a
    comment or a docstring no longer counts as a reference.
    """
    import io
    import tokenize

    names = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.NAME:
                names.add(tok.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # Unparseable file: fall back to substring, which over-exempts rather
        # than over-reports. Stated so the limit is visible.
        return None
    return names


def _violations():
    """(file, constant) pairs quoting >=2 members without referencing it."""
    found = []
    for rel in _py_files():
        text = open(os.path.join(_ROOT, rel), encoding="utf-8").read()
        names = _code_names(text)
        # This file declares VOCABULARIES, so it necessarily quotes every
        # member of every vocabulary. Structural exemption, not a baseline
        # entry: the registry cannot be a duplicate of itself.
        if rel.replace("\\", "/") == "tests/" + os.path.basename(__file__):
            continue
        for const, (owner, members) in VOCABULARIES.items():
            if rel.replace("\\", "/") == owner.replace("\\", "/"):
                continue
            if const in names if names is not None else const in text:
                continue
            quoted = {m for m in members
                      if re.search(r'(["\'])' + re.escape(m) + r'\1', text)}
            if len(quoted) >= 2:
                found.append((rel.replace("\\", "/"), const, sorted(quoted)))
    return found


def test_every_vocabulary_constant_still_exists():
    """If a constant is renamed, its check must fail loudly, not go quiet.

    VOCABULARIES is a hand-maintained list — the exact shape this file exists
    to distrust. This is the guard on the guard.
    """
    missing = []
    for const, (owner, _members) in VOCABULARIES.items():
        path = os.path.join(_ROOT, owner)
        if not os.path.exists(path):
            missing.append(f"{const}: owner {owner} does not exist")
            continue
        text = open(path, encoding="utf-8").read()
        if not re.search(rf"^{re.escape(const)}\s*=", text, re.M):
            missing.append(f"{const}: not defined in {owner}")

    assert not missing, (
        "status vocabulary constant(s) moved or renamed, which silently "
        "disables their duplication check: " + "; ".join(missing)
    )


def test_no_new_duplicated_status_vocabulary():
    new = [(f, c, q) for f, c, q in _violations() if (f, c) not in KNOWN]

    assert not new, (
        "file(s) holding their own copy of a status vocabulary:\n"
        + "\n".join(f"  {f} duplicates {c} {q}" for f, c, q in new)
        + "\n\nImport the constant from its owning module instead. A test that "
        "hardcodes a producer's status list stays green when the producer "
        "grows a state it has never heard of — that is how UNVERIFIABLE "
        "shipped with no CSS class."
    )


def test_baseline_has_no_stale_entries():
    """A fixed file must leave KNOWN, or the baseline rots into folklore."""
    current = {(f, c) for f, c, _q in _violations()}
    stale = sorted(k for k in KNOWN if k not in current)

    assert not stale, (
        "KNOWN lists duplication(s) that no longer exist — remove them so the "
        "baseline keeps meaning what it says: "
        + ", ".join(f"{f} / {c}" for f, c in stale)
    )
