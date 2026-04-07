#!/bin/bash
# Run after fresh clone: bash scripts/install-hooks.sh
set -e
HOOK=.git/hooks/pre-push
cat > "$HOOK" << 'HOOK_EOF'
#!/bin/bash
SCAN_PATTERN="192\.168\|10\.[0-9]\+\.\|172\.\(1[6-9]\|2[0-9]\|3[01]\)\.\|100\.\(6[4-9]\|[7-9][0-9]\|1[01][0-9]\|12[0-7]\)\.\|фролов\|frolov\|boris\|whis\|openclaw\|sberbank\|sber\|lanit\|/Users/\|@.*\.\(ru\|local\)\|ngrok\|ghp_\|github_pat_\|AKIA\|session-2026\|gardener-2026"
echo "🔍 Scanning for private content before push..."
HITS=$(git ls-files | xargs grep -il "$SCAN_PATTERN" 2>/dev/null | grep -v "^\.git/")
if [ -n "$HITS" ]; then
    echo ""; echo "❌ PUSH BLOCKED — private content detected in:"; echo "$HITS"
    echo ""; echo "Run: grep -in \"$SCAN_PATTERN\" $HITS"; exit 1
fi
echo "✅ Clean — no private content found."
exit 0
HOOK_EOF
chmod +x "$HOOK"
echo "✅ Pre-push hook installed."
