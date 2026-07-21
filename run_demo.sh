#!/usr/bin/env bash
# The Advocate Demo — repo-root entry point.
# Delegates to demo/advocate-demo/run_demo.sh so a cold clone just works:
#     git clone <url> && cd pcis && ./run_demo.sh
# Default (--replay) needs only Python (resolved stub-aware; zero deps, <60s).
# --live / --verify-self pass straight through.
set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
exec bash "$REPO/demo/advocate-demo/run_demo.sh" "$@"
