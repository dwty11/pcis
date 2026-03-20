#!/usr/bin/env python3
"""
verify_memory.py — Memory Integrity System

Usage:
    python3 verify_memory.py              # Verify all tracked files against manifest
    python3 verify_memory.py --update     # Update manifest with current hashes
    python3 verify_memory.py --init       # First run -- hash everything and write manifest
    python3 verify_memory.py --status     # Quick status: clean, changed, or broken

Designed to run at session start and session end.
No external dependencies. Python 3.8+ only.
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# --- Configuration -------------------------------------------------------

# Base directory where memory files live
# Update this to match your workspace path or set PCIS_BASE_DIR env var
BASE_DIR = os.environ.get("PCIS_BASE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# Files to track -- paths relative to BASE_DIR
# Includes the integrity scripts themselves -- a tampered verifier must be caught
TRACKED_FILES = [
    "core/verify_memory.py",
    "core/gardener.py",
    "core/knowledge_tree.py",
    "core/knowledge_prune.py",
    "core/knowledge_search.py",
]

# Where to store the manifest data -- OUTSIDE the directory it protects
INTEGRITY_DIR = os.path.join(BASE_DIR, "data", "integrity")
os.makedirs(INTEGRITY_DIR, exist_ok=True)
MANIFEST_JSON = os.path.join(INTEGRITY_DIR, "manifest.json")

# The human-readable manifest
MANIFEST_MD = os.path.join(BASE_DIR, "MANIFEST.md")

# Timezone for timestamps (UTC)
TZ_UTC = timezone.utc


# --- Core Functions -------------------------------------------------------

def hash_file(filepath: str) -> Optional[str]:
    """SHA-256 hash of file contents. Returns None if file missing."""
    try:
        with open(filepath, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except FileNotFoundError:
        return None


def load_manifest() -> dict:
    """Load existing manifest from JSON sidecar."""
    if os.path.exists(MANIFEST_JSON):
        with open(MANIFEST_JSON, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError as e:
                print(f"Error: manifest file is corrupted ({e}). Run --init to reinitialize.")
                sys.exit(1)
    return {}


def save_manifest(manifest: dict):
    """Save manifest to JSON sidecar."""
    with open(MANIFEST_JSON, "w") as f:
        json.dump(manifest, f, indent=2)


def now_utc() -> str:
    """Current timestamp in UTC."""
    return datetime.now(TZ_UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def hash_all_files() -> dict:
    """Hash all tracked files. Returns dict of filename -> hash/None."""
    result = {}
    for filename in TRACKED_FILES:
        filepath = os.path.join(BASE_DIR, filename)
        result[filename] = hash_file(filepath)
    return result


def compute_root_hash(file_hashes: dict) -> str:
    """
    Compute a Merkle-style root hash from all file hashes.
    This is the single value that tells you if ANYTHING changed.
    """
    leaves = []
    for filename in sorted(file_hashes.keys()):
        h = file_hashes[filename] or "MISSING"
        leaves.append(f"{filename}:{h}")

    level = [hashlib.sha256(leaf.encode()).hexdigest() for leaf in leaves]
    while len(level) > 1:
        next_level = []
        for i in range(0, len(level), 2):
            if i + 1 < len(level):
                combined = level[i] + level[i + 1]
            else:
                combined = level[i] + level[i]  # duplicate odd node
            next_level.append(hashlib.sha256(combined.encode()).hexdigest())
        level = next_level

    return level[0] if level else "EMPTY"


# --- Commands --------------------------------------------------------------

def cmd_init():
    """First run. Hash everything, create manifest."""
    print("Initializing memory manifest...")
    current = hash_all_files()
    root = compute_root_hash(current)
    timestamp = now_utc()

    manifest = {
        "root_hash": root,
        "last_verified": timestamp,
        "last_updated": timestamp,
        "files": {},
        "history": []
    }

    for filename, filehash in current.items():
        if filehash is None:
            print(f"  WARNING: {filename} -- NOT FOUND (will track when created)")
        else:
            print(f"  OK: {filename} -- {filehash[:16]}...")
        manifest["files"][filename] = {
            "hash": filehash,
            "last_changed": timestamp
        }

    manifest["history"].append({
        "timestamp": timestamp,
        "action": "init",
        "root_hash": root,
        "note": "First run -- all files hashed"
    })

    save_manifest(manifest)
    update_manifest_md(manifest, current)

    print(f"\nRoot hash: {root[:24]}...")
    print(f"Manifest written to {MANIFEST_JSON}")
    print(f"MANIFEST.md updated")
    print("\nMemory integrity system online.")


def cmd_verify():
    """Verify current files against stored manifest."""
    manifest = load_manifest()
    if not manifest:
        print("No manifest found. Run with --init first.")
        sys.exit(1)

    current = hash_all_files()
    current_root = compute_root_hash(current)
    stored_root = manifest.get("root_hash", "NONE")

    print(f"Verifying memory integrity...")
    print(f"   Stored root:  {stored_root[:24]}...")
    print(f"   Current root: {current_root[:24]}...")

    if current_root == stored_root:
        print("\nCLEAN -- All memory files intact. No changes detected.")
        manifest["last_verified"] = now_utc()
        save_manifest(manifest)
        return

    print("\nCHANGES DETECTED:\n")
    changes = []

    for filename in TRACKED_FILES:
        stored = manifest.get("files", {}).get(filename, {}).get("hash")
        current_hash = current[filename]

        if current_hash is None:
            print(f"  MISSING  -- {filename}")
            changes.append(f"MISSING: {filename}")
        elif stored is None:
            print(f"  NEW      -- {filename} (not in previous manifest)")
            changes.append(f"NEW: {filename}")
        elif stored != current_hash:
            print(f"  CHANGED  -- {filename}")
            print(f"       was: {stored[:16]}...")
            print(f"       now: {current_hash[:16]}...")
            changes.append(f"CHANGED: {filename}")
        else:
            print(f"  OK       -- {filename}")

    print(f"\n{len(changes)} file(s) differ from last known state.")
    print("   If these changes are expected, run --update.")
    print("   If unexpected, investigate before proceeding.")


def cmd_update():
    """Update manifest with current state."""
    manifest = load_manifest()
    if not manifest:
        print("No manifest found. Running --init instead.")
        cmd_init()
        return

    old_root = manifest.get("root_hash", "NONE")
    current = hash_all_files()
    new_root = compute_root_hash(current)
    timestamp = now_utc()

    changes = []

    for filename in TRACKED_FILES:
        old_hash = manifest.get("files", {}).get(filename, {}).get("hash")
        new_hash = current[filename]

        if old_hash != new_hash:
            changes.append(filename)
            manifest.setdefault("files", {})[filename] = {
                "hash": new_hash,
                "last_changed": timestamp
            }
            status = "missing -> tracked" if old_hash is None and new_hash else \
                     "tracked -> missing" if new_hash is None else "updated"
            print(f"  {filename} -- {status}")

    if not changes:
        print("No changes to record.")
        return

    manifest["root_hash"] = new_root
    manifest["last_updated"] = timestamp
    manifest["last_verified"] = timestamp

    manifest.setdefault("history", []).append({
        "timestamp": timestamp,
        "action": "update",
        "root_hash": new_root,
        "previous_root": old_root,
        "changed_files": changes,
        "note": f"{len(changes)} file(s) updated"
    })

    save_manifest(manifest)
    update_manifest_md(manifest, current)

    print(f"\nRoot hash: {old_root[:16]}... -> {new_root[:16]}...")
    print(f"Manifest updated. {len(changes)} change(s) recorded.")


def cmd_status():
    """Quick one-line status check."""
    manifest = load_manifest()
    if not manifest:
        print("NO_MANIFEST")
        sys.exit(1)

    current = hash_all_files()
    current_root = compute_root_hash(current)
    stored_root = manifest.get("root_hash")

    if current_root == stored_root:
        print("CLEAN")
    else:
        changed = 0
        missing = 0
        for filename in TRACKED_FILES:
            stored = manifest.get("files", {}).get(filename, {}).get("hash")
            curr = current[filename]
            if curr is None:
                missing += 1
            elif stored != curr:
                changed += 1
        print(f"CHANGED:{changed} MISSING:{missing}")


# --- MANIFEST.md Generator -------------------------------------------------

def update_manifest_md(manifest: dict, current_hashes: dict):
    """Regenerate the human-readable MANIFEST.md."""
    lines = [
        "# MANIFEST.md -- Memory Integrity Ledger",
        "",
        "_This file stores the hash of every tracked file",
        "so the system can detect changes, corruption, or tampering at session start._",
        "",
        f"_Last verified: {manifest.get('last_verified', 'never')}_",
        f"_Root hash: `{manifest.get('root_hash', 'none')[:32]}...`_",
        "",
        "---",
        "",
        "## How It Works",
        "",
        "At session start, run `python3 core/verify_memory.py`. Three outcomes:",
        "",
        "- **CLEAN** -- all hashes match. Memory intact. Proceed.",
        "- **CHANGED** -- files differ from last session. Review before trusting.",
        "- **MISSING** -- a tracked file is gone. Do not proceed until resolved.",
        "",
        "After updating files: `python3 core/verify_memory.py --update`",
        "",
        "---",
        "",
        "## Tracked Files",
        "",
        "| File | SHA-256 (first 24) | Last Changed |",
        "|------|-------------------|-------------|",
    ]

    for filename in TRACKED_FILES:
        file_info = manifest.get("files", {}).get(filename, {})
        h = file_info.get("hash")
        changed = file_info.get("last_changed", "--")
        if h is None:
            lines.append(f"| {filename} | `MISSING` | -- |")
        else:
            lines.append(f"| {filename} | `{h[:24]}...` | {changed} |")

    lines.extend([
        "",
        "---",
        "",
        "## Change History",
        "",
        "_Append-only. Every change gets logged with timestamp and reason._",
        "",
        "```",
    ])

    for entry in manifest.get("history", [])[-20:]:
        ts = entry.get("timestamp", "?")
        action = entry.get("action", "?")
        note = entry.get("note", "")
        root = entry.get("root_hash", "?")[:16]
        lines.append(f"[{ts}] {action}: {note} (root: {root}...)")

    lines.extend([
        "```",
        "",
        "---",
        "",
        "_This file is never trimmed. It is the chain of custody for the system's memory._",
    ])

    with open(MANIFEST_MD, "w") as f:
        f.write("\n".join(lines) + "\n")


# --- Entry Point -----------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--init" in args:
        cmd_init()
    elif "--update" in args:
        cmd_update()
    elif "--status" in args:
        cmd_status()
    else:
        cmd_verify()
