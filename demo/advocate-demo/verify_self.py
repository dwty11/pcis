#!/usr/bin/env python3
"""
verify_self.py — provenance guard for the Advocate Demo.

SHA-256 every demo script and fixture, compare to CANONICAL_FINGERPRINT.txt. A
skeptic runs this to confirm the code and the recorded run they're looking at are
the ones that were committed — the exact check the Liar's Demo shipped, plus (this
time) a CI test that asserts the fingerprint matches, so a hygiene edit to a
fingerprinted file can never diverge silently (the `39df68e` regression class).

  python3 verify_self.py           # compare to CANONICAL_FINGERPRINT.txt
  python3 verify_self.py --write    # (re)generate CANONICAL_FINGERPRINT.txt
"""
import difflib
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CANON = os.path.join(HERE, "CANONICAL_FINGERPRINT.txt")

# Everything a skeptic must be able to trust is unchanged. Order is stable.
FILES = [
    "generate_fixture.py",
    "record_canonical.py",
    "replay.py",
    "verdict.py",
    "verify_self.py",
    "run_demo.sh",
    "fixtures/seed_tree.json",
    "fixtures/PLANT_ID.txt",
    "fixtures/base/memory/2026-07-17.md",
    "fixtures/canonical_run.json",
    "fixtures/hit_rate.json",
]


def fingerprint():
    lines = []
    for rel in FILES:
        p = os.path.join(HERE, rel)
        if os.path.exists(p):
            h = hashlib.sha256(open(p, "rb").read()).hexdigest()
        else:
            h = "MISSING".ljust(64, "-")
        lines.append(f"{h}  {rel}")
    return "\n".join(lines)


def main():
    fp = fingerprint()
    if "--write" in sys.argv:
        with open(CANON, "w") as f:
            f.write(fp + "\n")
        print(f"wrote {CANON}")
        return 0
    print(fp)
    if not os.path.exists(CANON):
        print("\nNo CANONICAL_FINGERPRINT.txt to compare against "
              "(run with --write to create it).", file=sys.stderr)
        return 1
    canon = open(CANON).read().strip()
    if fp.strip() == canon:
        print("\n✓ verify-self: every script + fixture matches "
              "CANONICAL_FINGERPRINT.txt")
        return 0
    print("\n✗ verify-self: MISMATCH — a script or fixture differs from the "
          "committed canonical fingerprint:", file=sys.stderr)
    for line in difflib.unified_diff(
            canon.splitlines(), fp.strip().splitlines(),
            fromfile="CANONICAL_FINGERPRINT.txt", tofile="run_demo.sh --verify-self",
            lineterm=""):
        print("  " + line, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
