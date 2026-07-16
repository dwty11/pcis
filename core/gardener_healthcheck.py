#!/usr/bin/env python3
"""
gardener_healthcheck.py — Operational monitoring for the gardener.

Checks whether the gardener ran recently and completed successfully.
If not, writes a warning flag that downstream consumers (e.g. briefing) can pick up.

Usage:
    python3 gardener_healthcheck.py

Environment variables:
    PCIS_BASE_DIR — repo root (required for log/flag paths)
"""

import logging
import os
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pcis.gardener_healthcheck")

BASE_DIR = os.environ.get(
    "PCIS_BASE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."),
)
LOG_FILE = os.path.join(BASE_DIR, "data", "gardener-last.log")
FLAG_FILE = os.path.join(BASE_DIR, "data", "gardener-health.flag")


def probe():
    """Classify gardener health and return (status, detail). READ-ONLY.

    Reads gardener-last.log and classifies the last run. Does NOT write the
    health flag or log — safe for status reporting. Use check() when you also
    want the flag written/cleared (e.g. the `healthcheck` command)."""
    now = datetime.now()

    if not os.path.exists(LOG_FILE):
        return "MISSING", f"gardener-last.log does not exist at {LOG_FILE}"

    mtime = datetime.fromtimestamp(os.path.getmtime(LOG_FILE))
    age_hours = (now - mtime).total_seconds() / 3600
    if age_hours > 24:
        return "STALE", f"gardener-last.log last modified {age_hours:.1f}h ago (expected <24h)"

    with open(LOG_FILE) as f:
        raw = f.read()
    # Split on run boundary — take only the last run
    runs = raw.split("Gardener starting")
    last_run = "Gardener starting" + runs[-1] if len(runs) > 1 else raw
    if "Gardening complete" in last_run or "DRY RUN complete" in last_run:
        return "OK", f"Last run succeeded (log updated {age_hours:.1f}h ago)"
    if any(
        marker in last_run
        for marker in ["ERROR", "not found", "TimeoutError", "Traceback"]
    ):
        detail = "Last run contains errors -- check gardener-last.log"
        for line in reversed(last_run.strip().splitlines()):
            if any(x in line for x in ["ERROR", "not found", "TimeoutError", "Traceback"]):
                detail = line.strip()[:200]
                break
        return "ERROR", detail
    return "UNKNOWN", "Log updated but no success/error marker found in last run"


def check():
    """Run the healthcheck, WRITE the health flag, and return (status, detail).

    Side-effecting: on OK it clears the flag; otherwise it writes
    gardener-health.flag so downstream consumers (e.g. briefing) can pick it
    up, and logs the result. For read-only status reporting, use probe()."""
    status, detail = probe()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    if status == "OK":
        if os.path.exists(FLAG_FILE):
            os.remove(FLAG_FILE)
        log.info("Gardener health: OK -- %s", detail)
    else:
        os.makedirs(os.path.dirname(FLAG_FILE), exist_ok=True)
        with open(FLAG_FILE, "w") as f:
            f.write(f"GARDENER HEALTH: {status}\n")
            f.write(f"Checked: {timestamp}\n")
            f.write(f"Detail: {detail}\n")
            f.write("Action: Check gardener-last.log and rerun manually if needed.\n")
        log.warning("Gardener health: %s -- %s", status, detail)
        log.info("Flag written: %s", FLAG_FILE)

    return status, detail


def main():
    check()


if __name__ == "__main__":
    main()
