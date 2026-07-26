#!/usr/bin/env python3
"""Regenerate demo/demo_manifest.json — the baseline the boot check compares against.

Run after any intentional change to a tracked demo file:

    python3 demo/make_manifest.py

Without a manifest the boot check has nothing to compare against and reports
NO_MANIFEST for every file. It deliberately does not fall back to "OK": a green
tick with nothing behind it is the defect this file exists to close.

The manifest records what the files were when someone last vouched for them.
It cannot tell an authorised edit from tampering — it tells you the bytes moved
since that moment, which is the whole and only claim.
"""

import hashlib
import json
import os
import sys

DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(DEMO_DIR, "demo_manifest.json")

# Kept in step with server.DEMO_TRACKED_FILES; imported rather than copied so
# the two lists cannot drift apart.
sys.path.insert(0, os.path.dirname(DEMO_DIR))


def build():
    from demo.server import DEMO_TRACKED_FILES

    files, missing = {}, []
    for name in DEMO_TRACKED_FILES:
        path = os.path.join(DEMO_DIR, name)
        if not os.path.exists(path):
            missing.append(name)
            continue
        with open(path, "rb") as f:
            files[name] = hashlib.sha256(f.read()).hexdigest()
    return files, missing


def main():
    files, missing = build()
    if missing:
        print(f"⚠️  tracked file(s) not found, omitted from manifest: {missing}")
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump({"files": files}, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"✅ wrote {MANIFEST} ({len(files)} file(s))")
    for name, h in sorted(files.items()):
        print(f"   {h[:24]}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
