#!/bin/bash
# Control suite for the pre-push gate.  Run: bash scripts/test-hooks.sh
#
# WHY THIS EXISTS. On 2026-08-15 the gate's author wrote five controls, all green,
# and an independent adversarial pass then defeated the gate EIGHT ways. Every one
# of those bypasses is a case below. A gate is only worth what its controls have
# survived, and controls written by the author certify the author's model — so
# these are kept as regression cases and added to whenever something gets past.
#
# NO REAL FORBIDDEN TERM APPEARS IN THIS FILE. The suite points HOME at a sandbox
# and writes a SYNTHETIC operator pattern there, so it exercises the operator path
# without embedding a term this repository must not contain. That is deliberate: a
# test fixture is still a published line.
set -u

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
SANDBOX="${TMPDIR:-/tmp}/pcis-hooktest-$$-$(date +%s)"
TERM_OP="zzsynthopterm"          # stands in for an operator name
TERM_BUILTIN="ngrok"             # a real built-in pattern, safe to write down
WAIVER="i-have-read-the-recorded-exceptions"

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "$2"; }

# expect <want-exit> <name> -- <push args...>
expect() {
    local want=$1 name=$2; shift 3
    local out; out=$("$@" 2>&1); local got=$?
    if [ "$got" -eq "$want" ]; then ok "$name"
    else bad "$name" "wanted exit $want, got $got — $(printf '%s' "$out" | tr '\n' ' ' | cut -c1-160)"; fi
}

mkdir -p "$SANDBOX"
printf '%s\n' "$TERM_OP" > "$SANDBOX/.pcis-scan-patterns"
export HOME="$SANDBOX"           # the hook reads $HOME/.pcis-scan-patterns

cd "$SANDBOX" || exit 2
git init -q --bare bare.git
git clone -q "$REPO_ROOT" work 2>/dev/null || { echo "clone failed"; exit 2; }
cd work || exit 2
git config user.email t@example.invalid; git config user.name test
git remote remove origin 2>/dev/null
git remote add local "$SANDBOX/bare.git"
cp "$REPO_ROOT/scripts/install-hooks.sh" scripts/install-hooks.sh 2>/dev/null || true
bash scripts/install-hooks.sh > /dev/null

echo "pre-push gate controls"
echo "  sandbox: $SANDBOX"

# Establish the remote once. Pre-gate history is knowingly exempt (recorded).
PCIS_PUBLISH_HISTORY="$WAIVER" git push -q local main > /dev/null 2>&1
BASE=$(git rev-parse HEAD)

reset() { git reset -q --hard local/main >/dev/null 2>&1; git clean -qfd >/dev/null 2>&1; }

# ── the author's original five ───────────────────────────────────────────────
reset; echo "clean" > c1.txt; git add -A; git commit -qm "clean change"
expect 0 "clean incremental push passes" -- git push local main
git push -q local main >/dev/null 2>&1

reset; printf 'x = "%s"\n' "$TERM_OP" > c2.py; git add -A; git commit -qm "term in tip"
expect 1 "operator term in tip commit content is refused" -- git push local main

reset; printf 'x = "%s"\n' "$TERM_OP" > c3.py; git add -A; git commit -qm add
git rm -q c3.py; git commit -qm "removed again — tip is clean"
expect 1 "term in an INTERMEDIATE commit (tip clean) is refused" -- git push local main

reset; printf '\n# %s\n' "$TERM_OP" >> tests/test_pcis.py; git add -A; git commit -qm "op term in excluded file"
expect 1 "operator term inside an EXCLUDED file is still refused" -- git push local main

reset; printf '\n# see %s docs\n' "$TERM_BUILTIN" >> tests/test_pcis.py; git add -A; git commit -qm "builtin in excluded file"
expect 0 "built-in pattern inside an excluded file is allowed" -- git push local main
git push -q local main >/dev/null 2>&1

# ── the eight the adversarial pass found (2026-08-15) ────────────────────────
reset; echo clean > c6.txt; git add -A; git commit -qm "deploy notes for $TERM_OP rollout"
expect 1 "BYPASS-1: term in a COMMIT MESSAGE is refused" -- git push local main

reset; git commit -q --allow-empty -m "chore($TERM_OP): nothing to see"
expect 1 "BYPASS-1b: EMPTY commit, term only in the message, is refused" -- git push local main

reset; git tag -a leaktag -m "release cut for $TERM_OP" >/dev/null 2>&1
expect 1 "BYPASS-2: term in an ANNOTATED TAG MESSAGE is refused" -- git push local leaktag
git tag -d leaktag >/dev/null 2>&1

reset
{ printf '\377'; printf 'minified config endpoint=%s done\n' "$TERM_OP"; } > c8.json
git add -A; git commit -qm "poisoned line"
expect 1 "BYPASS-3: invalid-UTF-8 line poisoning is refused (LC_ALL=C)" -- git push local main

reset; echo harmless > "notes-$TERM_OP.txt"; git add -A; git commit -qm "name carries it"
expect 1 "BYPASS-4: term in a FILE NAME is refused" -- git push local main

reset
git checkout -qb side "$BASE" 2>/dev/null
printf 'leak %s\n' "$TERM_OP" > c10.txt; git add -A; git commit -qm "on a side branch"
git update-ref "refs/remotes/local/side" HEAD          # forge the tracking ref
expect 1 "BYPASS-5: forged refs/remotes cannot zero a new-ref range" -- git push local side
git update-ref -d "refs/remotes/local/side" 2>/dev/null
git checkout -q main 2>/dev/null

reset
printf 'leak %s\n' "$TERM_OP" > c11.txt; git add -A; git commit -qm "rewind target"
expect 1 "BYPASS-6: force-push rewind is scanned, not skipped" -- git push --force local main

# ── the waiver must still work, and must be explicit ─────────────────────────
reset; echo clean > c12.txt; git add -A; git commit -qm "clean"
expect 0 "a clean push still passes after all of the above" -- git push local main

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
echo "sandbox left at $SANDBOX (delete it yourself; this script never removes trees)"
[ "$FAIL" -eq 0 ]
