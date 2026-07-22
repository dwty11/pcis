"""Russian-locale (cp1251) Windows portability for the hash path and the CLI.

A cold-read on Russian-Windows hit two failures the Western-locale tests missed:
  1. `./verify.sh` reported ✗ TAMPERED on a fresh, unmodified clone — because the tree
     is read with an unqualified open() (cp1251 default on RU-Windows), so its non-ASCII
     content mis-decodes and every re-derived leaf hash mismatches. And the reverse: a
     tree WRITTEN under cp1251 can't be verified on a UTF-8 host.
  2. `pcis verify` crashed with UnicodeEncodeError printing an emoji to a cp1251 console.

Reproduced ON A UNIX HOST by forcing cp1251 as the default text encoding (and, for the
crash test, a strict cp1251 stdout) in a fresh subprocess before any project import.
Acceptance: a clean tree verifies CLEAN under cp1251, a MODIFIED tree still verifies
TAMPERED (the demo must keep working), and the CLI does not crash.
"""
import json
import os
import subprocess
import sys
import textwrap

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(body, tmp, strict_cp1251_stdout=False):
    """Run `body` in a fresh subprocess with cp1251 forced as the default open() encoding."""
    boot = textwrap.dedent(f"""
        import sys, os, builtins, io, json
        REPO, TMP = {REPO!r}, {str(tmp)!r}
        _open = builtins.open
        def _win_open(file, mode="r", buffering=-1, encoding=None, *a, **k):
            if "b" not in mode and encoding is None:
                encoding = "cp1251"            # Russian-locale Windows default
            return _open(file, mode, buffering, encoding, *a, **k)
        builtins.open = _win_open
    """)
    if strict_cp1251_stdout:
        boot += ('sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="cp1251",'
                 ' errors="strict", line_buffering=True)\n')
    boot += ("sys.path.insert(0, os.path.join(REPO, 'core'))\n"
             "sys.path.insert(0, REPO)\n")
    boot += textwrap.dedent(body)
    env = dict(os.environ, PCIS_BASE_DIR=str(tmp),
               PCIS_TREE_FILE=os.path.join(str(tmp), "data", "tree.json"))
    return subprocess.run([sys.executable, "-c", boot], capture_output=True, text=True, env=env)


def _seed_tree_with_nonascii(tmp):
    """A UTF-8 tree carrying non-ASCII content (em-dash, section sign) — the bytes that
    mis-decode under cp1251. Written by a KNOWN-GOOD (UTF-8) writer."""
    d = os.path.join(tmp, "data")
    os.makedirs(d, exist_ok=True)
    sys.path.insert(0, os.path.join(REPO, "core"))
    import knowledge_tree as kt
    tree = kt.load_tree(os.path.join(d, "tree.json"))  # fresh empty
    kt.add_knowledge(tree, "precedent", "Ruling — §2 waiver does not apply here", confidence=0.9)
    kt.add_knowledge(tree, "precedent", "Second leaf — plain ASCII", confidence=0.8)
    kt.save_tree(tree, os.path.join(d, "tree.json"))
    return os.path.join(d, "tree.json")


def test_clean_tree_verifies_CLEAN_under_cp1251(tmp_path):
    _seed_tree_with_nonascii(tmp_path)
    r = _run("""
        import knowledge_tree as kt
        tree = kt.load_tree(os.path.join(TMP, "data", "tree.json"))
        ok, errs = kt.verify_tree_integrity(tree)
        print("CLEAN" if ok else "TAMPERED:" + repr(errs)[:200])
    """, tmp_path)
    assert r.returncode == 0, r.stderr
    assert "CLEAN" in r.stdout, f"clean tree falsely reported tampered under cp1251:\n{r.stdout}\n{r.stderr}"


def test_modified_tree_still_verifies_TAMPERED_under_cp1251(tmp_path):
    tree_path = _seed_tree_with_nonascii(tmp_path)
    # Flip one content byte with a UTF-8 writer (real modification, not an encoding artifact).
    t = json.load(open(tree_path, encoding="utf-8"))
    first = t["branches"]["precedent"]["leaves"][0]
    first["content"] = first["content"] + " TAMPERED"
    json.dump(t, open(tree_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    r = _run("""
        import knowledge_tree as kt
        tree = kt.load_tree(os.path.join(TMP, "data", "tree.json"))
        ok, errs = kt.verify_tree_integrity(tree)
        print("CLEAN" if ok else "TAMPERED")
    """, tmp_path)
    assert r.returncode == 0, r.stderr
    assert "TAMPERED" in r.stdout, f"a genuinely modified tree must still report TAMPERED:\n{r.stdout}"


def test_tree_written_under_cp1251_verifies_on_utf8(tmp_path):
    """Write side: a tree written on RU-Windows must verify on a UTF-8 host, and vice versa."""
    r = _run("""
        import knowledge_tree as kt
        p = os.path.join(TMP, "data", "tree.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tree = kt.load_tree(p)
        kt.add_knowledge(tree, "precedent", "Written under cp1251 — §3 and an em-dash", confidence=0.9)
        kt.save_tree(tree, p)
        print("WROTE")
    """, tmp_path)
    assert "WROTE" in r.stdout, r.stderr
    # Now read + verify with a UTF-8 host (this test process).
    sys.path.insert(0, os.path.join(REPO, "core"))
    import knowledge_tree as kt
    tree = kt.load_tree(os.path.join(tmp_path, "data", "tree.json"))
    ok, errs = kt.verify_tree_integrity(tree)
    assert ok, f"a cp1251-written tree failed UTF-8 verification (write-side encoding bug): {errs}"


def test_cli_verify_does_not_crash_on_cp1251_console(tmp_path):
    _seed_tree_with_nonascii(tmp_path)
    r = _run("""
        import runpy
        sys.argv = ["pcis", "--dir", TMP, "verify"]
        try:
            runpy.run_module("pcis.cli", run_name="__main__")
        except SystemExit:
            pass
    """, tmp_path, strict_cp1251_stdout=True)
    assert "UnicodeEncodeError" not in r.stderr, f"CLI crashed encoding output to a cp1251 console:\n{r.stderr}"
