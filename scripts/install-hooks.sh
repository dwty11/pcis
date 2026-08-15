#!/bin/bash
# Run after fresh clone: bash scripts/install-hooks.sh
# Installs a pre-push hook that scans the CONTENT BEING PUSHED for leak patterns.
# To add your own private patterns, create ~/.pcis-scan-patterns (one regex per line).
set -e
HOOK=.git/hooks/pre-push
cat > "$HOOK" << 'HOOK_EOF'
#!/bin/bash
# Refuses a push that would publish a leak pattern.
#
# ⚠️ EVERY RULE BELOW EXISTS BECAUSE SOMETHING GOT PAST AN EARLIER VERSION.
# An adversarial pass on 2026-08-15 defeated this gate eight ways while its
# author's own five controls were green. Do not simplify any of this without
# re-running scripts/test-hooks.sh, which encodes each of those bypasses.
#
# BYTE-ORIENTED LOCALE — NOT COSMETIC. Under a UTF-8 locale, BSD grep silently
# skips an ENTIRE LINE containing an invalid byte. One 0xFF at the top of a
# minified file hid every term in it from both scans. LC_ALL=C makes grep
# byte-oriented so no encoding artefact can mask content.
export LC_ALL=C LANG=C

# Built-in patterns catch universal leak shapes: private IPs, local user paths,
# tunnel URLs, and well-known API key prefixes. Operator-specific names (people,
# org, project codenames) belong in ~/.pcis-scan-patterns, not in this script —
# putting them here would publish the very terms the gate exists to keep out.
BUILTIN='192\.168\.\|10\.[0-9]\+\.\|172\.\(1[6-9]\|2[0-9]\|3[01]\)\.\|/Users/\|ngrok\|ghp_[A-Za-z0-9]\{36\}\|github_pat_\|AKIA[0-9A-Z]\{16\}\|sk_live_'
USER_PATTERNS="$HOME/.pcis-scan-patterns"

# Files that carry BUILT-IN patterns as FIXTURES and would trip the scan on
# themselves. ⚠️ THE EXCLUSIONS APPLY TO BUILT-IN PATTERNS ONLY — operator names
# are scanned everywhere, with no exemption. A test fixture may legitimately
# contain "/users/"; nothing legitimately contains a person's name or a project
# codename, and this repo's one recorded history exception sits in an excluded
# file, which is exactly why the exemption must not extend to the operator set.
EXCLUDE='^scripts/install-hooks\.sh$|^scripts/test-hooks\.sh$|^tests/test_pcis\.py$|^tests/test_events\.py$'

OPERATOR=""
if [ -r "$USER_PATTERNS" ]; then
    OPERATOR=$(grep -v '^#' "$USER_PATTERNS" 2>/dev/null | grep -v '^$' | tr '\n' '|' | sed 's/|$//')
fi
if [ -n "$OPERATOR" ]; then
    echo "pre-push: built-in patterns + operator patterns from $USER_PATTERNS"
else
    echo "pre-push: WARNING — no $USER_PATTERNS; scanning for BUILT-IN patterns only."
    echo "pre-push: people, org and project names are NOT covered by this scan."
fi

FAILED=0
report() { echo "PUSH BLOCKED — $1:"; echo "$2"; FAILED=1; }

# op_hit / builtin_hit: read from a FILE or stdin, never a pipe into a loop.
op_hit()      { [ -n "$OPERATOR" ] && grep -qi "$OPERATOR" ; }
builtin_hit() { grep -qi "$BUILTIN" ; }

# ── 1. working tree ──────────────────────────────────────────────────────────
WT_BUILTIN=$(git ls-files | grep -Ev "$EXCLUDE" | tr '\n' '\0' | xargs -0 grep -il "$BUILTIN" 2>/dev/null | grep -v '^\.git/' || true)
[ -n "$WT_BUILTIN" ] && report "built-in pattern in working tree" "$WT_BUILTIN"
if [ -n "$OPERATOR" ]; then
    WT_OP=$(git ls-files | tr '\n' '\0' | xargs -0 grep -il "$OPERATOR" 2>/dev/null | grep -v '^\.git/' || true)
    [ -n "$WT_OP" ] && report "operator pattern in working tree" "$WT_OP"
    # Names, not just content: a file NAMED for a term publishes the term.
    WT_NAMES=$(git ls-files | grep -i "$OPERATOR" || true)
    [ -n "$WT_NAMES" ] && report "operator pattern in a tracked PATH" "$WT_NAMES"
fi

# ── 2. everything the push would publish ─────────────────────────────────────
ZERO='0000000000000000000000000000000000000000'
TMPD=$(mktemp -d)
trap 'rm -f "$TMPD"/objs "$TMPD"/msgs 2>/dev/null; rmdir "$TMPD" 2>/dev/null' EXIT

while read -r local_ref local_sha remote_ref remote_sha; do
    [ -z "$local_sha" ] && continue
    [ "$local_sha" = "$ZERO" ] && continue          # deletion publishes nothing

    FULL=0
    if [ "$remote_sha" = "$ZERO" ]; then
        FULL=1                                       # new ref = new publication
    elif ! git merge-base --is-ancestor "$remote_sha" "$local_sha" 2>/dev/null; then
        # Force-push / rewind. The two-dot range would be EMPTY and the push
        # would sail through while republishing a rewritten tip.
        echo "pre-push: NON-FAST-FORWARD on $local_ref — scanning full history."
        FULL=1
    fi

    if [ "$FULL" -eq 1 ]; then
        if [ "$PCIS_PUBLISH_HISTORY" = "i-have-read-the-recorded-exceptions" ]; then
            echo "pre-push: full-history scan waived by PCIS_PUBLISH_HISTORY for $local_ref."
            continue
        fi
        # NOT --not --remotes: refs/remotes/* is client-writable, so a pusher can
        # forge one at the commit being pushed and zero the range. The honest
        # range for a new publication is everything reachable.
        git rev-list --objects "$local_sha" > "$TMPD/objs" 2>/dev/null || true
        git rev-list "$local_sha" > "$TMPD/revs" 2>/dev/null || true
    else
        git rev-list --objects "$remote_sha..$local_sha" > "$TMPD/objs" 2>/dev/null || true
        git rev-list "$remote_sha..$local_sha" > "$TMPD/revs" 2>/dev/null || true
    fi

    # 2a. commit MESSAGES — type 'commit', emitted with no path, and therefore
    #     invisible to any blob-only walk. An empty commit carries no blob at all
    #     and still publishes its message.
    if [ -s "$TMPD/revs" ]; then
        if [ -n "$OPERATOR" ] && git log --no-walk --format='%B%n%an%n%ae' --stdin < "$TMPD/revs" 2>/dev/null | op_hit; then
            report "operator pattern in a commit message or author field" "  in range for $local_ref"
        fi
        if git log --no-walk --format='%B%n%an%n%ae' --stdin < "$TMPD/revs" 2>/dev/null | builtin_hit; then
            report "built-in pattern in a commit message or author field" "  in range for $local_ref"
        fi
    fi

    # 2b. PATH NAMES in the pushed objects — a filename is published text.
    if [ -n "$OPERATOR" ]; then
        NAME_HITS=$(cut -d' ' -f2- < "$TMPD/objs" | grep -i "$OPERATOR" | sort -u || true)
        [ -n "$NAME_HITS" ] && report "operator pattern in a pushed PATH" "$NAME_HITS"
    fi

    # 2c. object CONTENT — blob, commit AND tag. The tag object carries the
    #     annotation message; skipping non-blobs is how tag messages got through.
    while read -r sha path; do
        [ -z "$sha" ] && continue
        t=$(git cat-file -t "$sha" 2>/dev/null </dev/null) || continue
        case "$t" in blob|tag) ;; *) continue ;; esac
        label="${path:-<$t $sha>}"
        if [ -n "$OPERATOR" ] && git cat-file -p "$sha" 2>/dev/null </dev/null | op_hit; then
            report "operator pattern in a pushed $t" "  $label  ($sha)"
        fi
        case "$path" in
            scripts/install-hooks.sh|scripts/test-hooks.sh|tests/test_pcis.py|tests/test_events.py) ;;
            *)
                if git cat-file -p "$sha" 2>/dev/null </dev/null | builtin_hit; then
                    report "built-in pattern in a pushed $t" "  $label  ($sha)"
                fi
                ;;
        esac
    done < "$TMPD/objs"

    # 2d. the pushed ref may itself BE an annotated tag object not named by the
    #     object walk (tag pointing at an already-published commit → empty range).
    t=$(git cat-file -t "$local_sha" 2>/dev/null </dev/null || true)
    if [ "$t" = "tag" ]; then
        if [ -n "$OPERATOR" ] && git cat-file -p "$local_sha" 2>/dev/null </dev/null | op_hit; then
            report "operator pattern in the pushed tag object" "  $local_ref ($local_sha)"
        fi
        if git cat-file -p "$local_sha" 2>/dev/null </dev/null | builtin_hit; then
            report "built-in pattern in the pushed tag object" "  $local_ref ($local_sha)"
        fi
    fi
    # 2e. the ref NAME itself is published text.
    if [ -n "$OPERATOR" ] && printf '%s' "$local_ref" | op_hit; then
        report "operator pattern in the pushed REF NAME" "  $local_ref"
    fi
done

if [ "$FAILED" -ne 0 ]; then
    echo
    echo "Nothing was pushed. A term in a commit becomes permanent once published,"
    echo "so this refuses before the fact rather than reporting after it."
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
