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


def check():
    """Run the healthcheck and return (status, detail) tuple."""
    now = datetime.now()

    if not os.path.exists(LOG_FILE):
        status = "MISSING"
        detail = f"gardener-last.log does not exist at {LOG_FILE}"
    else:
        mtime = datetime.fromtimestamp(os.path.getmtime(LOG_FILE))
        age_hours = (now - mtime).total_seconds() / 3600
        if age_hours > 24:
            status = "STALE"
            detail = f"gardener-last.log last modified {age_hours:.1f}h ago (expected <24h)"
        else:
            with open(LOG_FILE) as f:
                raw = f.read()
            # Split on run boundary — take only the last run
            runs = raw.split("Gardener starting")
            last_run = "Gardener starting" + runs[-1] if len(runs) > 1 else raw
            if "Gardening complete" in last_run or "DRY RUN complete" in last_run:
                status = "OK"
                detail = f"Last run succeeded (log updated {age_hours:.1f}h ago)"
            elif any(
                marker in last_run
                for marker in ["ERROR", "not found", "TimeoutError", "Traceback"]
            ):
                status = "ERROR"
                detail = "Last run contains errors -- check gardener-last.log"
                for line in reversed(last_run.strip().splitlines()):
                    if any(x in line for x in ["ERROR", "not found", "TimeoutError", "Traceback"]):
                        detail = line.strip()[:200]
                        break
            else:
                status = "UNKNOWN"
                detail = "Log updated but no success/error marker found in last run"

    timestamp = now.strftime("%Y-%m-%d %H:%M UTC")

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
