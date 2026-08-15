#!/bin/bash
# Run after fresh clone: bash scripts/install-hooks.sh
# Installs a pre-push hook that scans staged content for common leak patterns.
# To add your own private patterns, create ~/.pcis-scan-patterns (one regex per line).
set -e
HOOK=.git/hooks/pre-push
cat > "$HOOK" << 'HOOK_EOF'
#!/bin/bash
# Built-in patterns catch universal leak shapes: private IPs, local user paths,
# tunnel URLs, and well-known API key prefixes. Operator-specific names (people,
# org, project codenames) belong in ~/.pcis-scan-patterns, not in this script.
BUILTIN='192\.168\.\|10\.[0-9]\+\.\|172\.\(1[6-9]\|2[0-9]\|3[01]\)\.\|/Users/\|ngrok\|ghp_[A-Za-z0-9]\{36\}\|github_pat_\|AKIA[0-9A-Z]\{16\}\|sk_live_'
USER_PATTERNS="$HOME/.pcis-scan-patterns"
PATTERN="$BUILTIN"
if [ -r "$USER_PATTERNS" ]; then
    EXTRA=$(grep -v '^#' "$USER_PATTERNS" 2>/dev/null | grep -v '^$' | tr '\n' '|' | sed 's/|$//')
    [ -n "$EXTRA" ] && PATTERN="$BUILTIN\\|$EXTRA"
    echo "pre-push: built-in patterns + operator patterns from $USER_PATTERNS"
else
    # Say so at push time, every time. A gate that quietly covers less than the
    # operator believes is worse than no gate: reinstalling this hook replaces
    # any hand-edited copy, so operator names that were only ever baked into
    # .git/hooks/pre-push disappear with no message and nothing looks different.
    echo "pre-push: WARNING — no $USER_PATTERNS; scanning for BUILT-IN patterns only."
    echo "pre-push: people, org and project names are NOT covered by this scan."
fi
# Files that carry leak patterns as FIXTURES and would otherwise trip the scan on
# themselves: this installer (it contains the patterns as strings) and the
# leak-detection tests (test_pcis.py:246 asserts redaction covers "/users/", which
# the case-insensitive scan matches). Without these exclusions a fresh clone's gate
# refuses every push, which trains the operator to bypass it — the failure mode a
# gate can least afford.
# EXPOSURE, stated rather than hidden: a real leak inside one of these three files
# is not scanned. They are small, they are reviewed, and the alternative is a gate
# nobody can push through.
EXCLUDE='^scripts/install-hooks\.sh$|^tests/test_pcis\.py$|^tests/test_events\.py$'
HITS=$(git ls-files | grep -Ev "$EXCLUDE" | xargs grep -il "$PATTERN" 2>/dev/null | grep -v "^\.git/" || true)
if [ -n "$HITS" ]; then
    echo "PUSH BLOCKED — private content detected in:"
    echo "$HITS"
    echo
    echo "Patterns matched: $PATTERN"
    exit 1
fi
exit 0
HOOK_EOF
chmod +x "$HOOK"
echo "Pre-push hook installed at $HOOK"
if [ -r "$HOME/.pcis-scan-patterns" ]; then
    echo "Operator patterns found at ~/.pcis-scan-patterns — they will be scanned too."
else
    echo
    echo "WARNING: ~/.pcis-scan-patterns not found."
    echo "  This install covers BUILT-IN patterns only: private IPs, local user paths,"
    echo "  tunnel URLs and API-key prefixes. It does NOT cover people, organisation or"
    echo "  project names. If a previous hook was hand-edited to include them, this"
    echo "  install has just replaced it and that coverage is gone."
    echo "  Create ~/.pcis-scan-patterns (one regex per line, # for comments) and re-run."
fi
