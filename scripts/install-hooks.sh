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
fi
HITS=$(git ls-files | grep -v "^scripts/install-hooks.sh$" | xargs grep -il "$PATTERN" 2>/dev/null | grep -v "^\.git/" || true)
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
echo "To add private patterns: create ~/.pcis-scan-patterns (one regex per line, # for comments)."
