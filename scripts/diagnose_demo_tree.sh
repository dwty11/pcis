#!/usr/bin/env bash
# PCIS demo_tree.json integrity diagnostic.
#
# If `bash start_demo.sh` reports "[2/5] ... demo_tree.json integrity FAILED" on a clean
# clone, run this from the repo (any directory):
#     bash scripts/diagnose_demo_tree.sh
#
# start_demo.sh's step 2 swallows the real error into a variable it only compares to "OK",
# so the failure is opaque. This prints: (1) the environment, (2) the file's byte-level
# state (working tree vs the committed blob — catches autocrlf/BOM/CRLF), (3) the EXACT
# step-2 computation with the hidden error and a stored-vs-recomputed hash, and (4) a
# relative-path control that isolates a MINGW/Git-Bash absolute-path problem.
set +e

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
cd "$REPO" || { echo "cannot cd to repo root ($REPO)"; exit 1; }

PY="$(REPO="$REPO" bash scripts/resolve_python.sh 2>/dev/null)"
[ -z "$PY" ] && PY="python"

echo "==================== 1. ENVIRONMENT ===================="
echo "REPO (bash pwd)        : $REPO"
command -v cygpath >/dev/null 2>&1 && echo "REPO (windows form)    : $(cygpath -w "$REPO" 2>/dev/null)"
git --version 2>&1 | head -1
echo "core.autocrlf          : $(git config --get core.autocrlf || echo '(unset -> Git-for-Windows default is true)')"
echo "core.eol               : $(git config --get core.eol || echo '(unset)')"
echo "resolved \$PYTHON       : $PY"
"$PY" -c "import sys,locale
print('python version         :', sys.version.split()[0])
print('sys.platform           :', sys.platform)
print('sys.executable         :', sys.executable)
print('sys.getdefaultencoding :', sys.getdefaultencoding())
print('locale.preferred       :', locale.getpreferredencoding(False))" 2>&1

echo
echo "==================== 2. FILE BYTE STATE ===================="
"$PY" - <<'PYEOF' 2>&1
import subprocess, hashlib
wt = open('demo/demo_tree.json', 'rb').read()
print('working-tree bytes     :', len(wt))
try:
    blob = subprocess.check_output(['git', 'cat-file', 'blob', 'HEAD:demo/demo_tree.json'])
    print('committed blob bytes   :', len(blob))
    print('working == committed?  :', wt == blob, '  (False => autocrlf/editor rewrote the file)')
    print('committed  blob sha256 :', hashlib.sha256(blob).hexdigest())
except Exception as e:
    print('could not read committed blob:', e)
print('working-tree sha256    :', hashlib.sha256(wt).hexdigest())
print('contains CRLF (\\r\\n)?   :', b'\r\n' in wt)
print('starts with UTF-8 BOM?  :', wt[:3] == b'\xef\xbb\xbf')
PYEOF

echo
echo "==================== 3. STEP 2, VERBATIM, WITH THE HIDDEN ERROR SHOWN ===================="
echo "   (start_demo.sh runs exactly this, but hides the result in a variable it compares to 'OK')"
"$PY" - "$REPO" <<'PYEOF' 2>&1
import sys, json, traceback
REPO = sys.argv[1]
abspath = REPO + '/demo/demo_tree.json'
print('path passed to open()  :', abspath)
sys.path.insert(0, REPO + '/core')
sys.path.insert(0, REPO)
try:
    from core.knowledge_tree import verify_tree_integrity, hash_leaf
    with open(abspath, encoding='utf-8') as f:
        tree = json.load(f)
    ok, errors = verify_tree_integrity(tree)
    print('RESULT                 :', 'CLEAN' if ok else 'FAIL')
    for e in (errors or [])[:5]:
        print('   ' + e)
    if not ok:
        for bn, b in tree.get('branches', {}).items():
            for lf in b.get('leaves', []):
                red = hash_leaf(lf['content'], bn, lf['created'])
                if red != lf.get('hash'):
                    print('   --- first mismatching leaf ---')
                    print('   branch / leaf       :', bn, '/', lf['id'][:8])
                    print('   stored hash         :', lf.get('hash'))
                    print('   re-derived hash     :', red)
                    print('   content repr        :', repr(lf['content'][:90]))
                    print('   content utf-8 bytes :', lf['content'][:45].encode('utf-8', 'backslashreplace'))
                    print('   created             :', repr(lf.get('created')))
                    sys.exit(0)
except SystemExit:
    pass
except Exception:
    print('EXCEPTION (this is what start_demo.sh swallows into $INTEGRITY):')
    traceback.print_exc()
PYEOF

echo
echo "==================== 4. RELATIVE-PATH CONTROL (isolates a MINGW absolute-path problem) ===================="
echo "   step 4 of start_demo.sh works because it does 'cd \$REPO' first, then uses relative paths."
"$PY" - <<'PYEOF' 2>&1
import sys, json, traceback
sys.path.insert(0, 'core'); sys.path.insert(0, '.')
try:
    from core.knowledge_tree import verify_tree_integrity
    with open('demo/demo_tree.json', encoding='utf-8') as f:   # RELATIVE path, cwd = repo root
        tree = json.load(f)
    ok, errors = verify_tree_integrity(tree)
    print('RELATIVE-path result   :', 'CLEAN' if ok else 'FAIL', (errors[0] if errors else ''))
    print('   => if this is CLEAN but section 3 (absolute path) FAILED, the bug is the MINGW')
    print('      absolute path passed to a native-Windows Python, NOT the file or its encoding.')
except Exception:
    print('EXCEPTION on the relative path too:')
    traceback.print_exc()
PYEOF
echo "==================== END ===================="
